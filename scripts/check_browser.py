"""Optional Chromium smoke check against a local, disposable application."""
from contextlib import contextmanager
from pathlib import Path
import tempfile
from threading import Thread

from playwright.sync_api import sync_playwright
from PIL import Image
from werkzeug.security import generate_password_hash
from werkzeug.serving import make_server, WSGIRequestHandler

from mortezkana import create_app
from mortezkana.db import get_db, migrate


class QuietHandler(WSGIRequestHandler):
    def log(self, _type, _message, *args):
        pass


@contextmanager
def live_server(app):
    server = make_server('127.0.0.1', 0, app, request_handler=QuietHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def main():
    with tempfile.TemporaryDirectory() as directory:
        app = create_app({'TESTING': True, 'SECRET_KEY': 'browser-test-only-' * 4,
                          'ADMIN_PASSWORD_HASH': generate_password_hash('browser-test-password'),
                          'DATABASE': str(Path(directory) / 'competition.sqlite3')})
        with app.app_context():
            migrate()
            with get_db() as db:
                db.executemany('INSERT INTO teams(name) VALUES (?)', [('Verde',), ('Azul',)])
                db.executemany('INSERT INTO participants(name, team_id) VALUES (?, ?)',
                               [(f'Persona {index}', 1 if index <= 5 else 2) for index in range(1, 11)])
                for challenge in range(1, 13):
                    db.execute("INSERT INTO challenges(id, name, kind, day, status, chronology_position) VALUES (?, ?, 'hybrid', ?, 'completed', ?)",
                               (challenge, f'Prueba {challenge}', 1 + challenge % 3, challenge))
                    db.executemany('INSERT INTO results(challenge_id, participant_id, points, notes) VALUES (?, ?, ?, ?)',
                                   [(challenge, person, 11 - person, 'Resultado de prueba') for person in range(1, 11)])
                    db.executemany('INSERT INTO results(challenge_id, team_id, points, notes) VALUES (?, ?, ?, ?)',
                                   [(challenge, 1, 3, 'Equipo ganador'), (challenge, 2, 1, 'Equipo perdedor')])
        with live_server(app) as base_url, sync_playwright() as playwright:
            photo_path = Path(directory) / 'test-avatar.png'
            Image.new('RGB', (400, 300), (70, 130, 110)).save(photo_path)
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))

            page.goto(f'{base_url}/')
            page.locator('#score-history').wait_for(state='visible')
            assert page.locator('.avatar').count() == 12
            assert page.locator('#score-history img').count() == 0
            assert page.locator('#history-plot polyline').count() == 10
            assert page.locator('.series-score').first.inner_text() == '120 pts'
            page.get_by_role('button', name='Equipos', exact=True).click()
            assert page.locator('#history-plot polyline').count() == 2
            assert page.locator('.series-score').first.inner_text() == '516 pts'
            page.locator('#history-step').select_option('1')
            assert page.locator('.series-score').first.inner_text() == '43 pts'
            page.locator('#history-legend input').first.uncheck()
            assert page.locator('#history-plot polyline').count() == 1
            page.locator('#history-legend input').nth(1).uncheck()
            assert page.locator('#history-plot polyline').count() == 0
            assert 'No hay series seleccionadas' in page.locator('#history-detail').inner_text()
            page.locator('#history-legend input').first.check()
            page.locator('#history-legend input').nth(1).check()
            page.locator('#history-plot').focus()
            page.keyboard.press('ArrowLeft')
            assert page.locator('#history-step').input_value() == '0'
            page.keyboard.press('ArrowRight')
            assert page.locator('#history-step').input_value() == '1'
            box = page.locator('#history-plot').bounding_box()
            page.locator('#history-plot').tap(position={'x': box['width'] * .75, 'y': 100})
            assert int(page.locator('#history-step').input_value()) > 1
            page.get_by_role('button', name='Personas', exact=True).click()
            assert page.locator('#history-plot polyline').count() == 10
            for width in (320, 390, 1280):
                page.set_viewport_size({'width': width, 'height': 900})
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), f'Overflow at {width}px'
            page.set_viewport_size({'width': 390, 'height': 844})
            page.locator('#score-history').screenshot(path='/tmp/mortezkana-history.png')
            page.goto(f'{base_url}/challenges')
            page.get_by_text('Chuleta de puntuaciones', exact=True).click()
            assert page.get_by_text('Victoria individual:', exact=False).is_visible()
            assert page.get_by_text('Puntuación individual en prueba mixta', exact=True).is_visible()
            assert page.goto(f'{base_url}/final').status == 404
            page.goto(f'{base_url}/admin/login')
            page.get_by_label('Contraseña').fill('browser-test-password')
            page.get_by_role('button', name='Entrar', exact=True).click()
            page.wait_for_url('**/admin')
            for kind in ('participants', 'teams'):
                photo_form = page.locator(f'form[action="/admin/avatars/{kind}/1"][enctype="multipart/form-data"]')
                page.locator('details').filter(has=photo_form).locator('summary').first.click()
                photo_form.locator('input[name="photo"]').set_input_files(str(photo_path))
                photo_form.get_by_role('button', name='Guardar avatar', exact=True).click()
                page.wait_for_url('**/admin')
                assert 'Avatar guardado.' in page.locator('main').inner_text()
            for path in ('/', '/participants'):
                page.goto(f'{base_url}{path}')
                for kind in ('participants', 'teams'):
                    image = page.locator(f'img[src="/avatars/{kind}/1"]').first
                    image.scroll_into_view_if_needed()
                    page.wait_for_function('selector => document.querySelector(selector).naturalWidth > 0', arg=f'img[src="/avatars/{kind}/1"]')
                for width in (320, 390, 1280):
                    page.set_viewport_size({'width': width, 'height': 900})
                    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), f'Avatar page overflow at {width}px'
                if path == '/':
                    assert page.locator('#score-history img').count() == 0
                else:
                    page.set_viewport_size({'width': 390, 'height': 844})
                    page.screenshot(path='/tmp/mortezkana-roster.png', full_page=True)
            page.goto(f'{base_url}/admin')
            inputs = page.locator('form[action="/admin/reorder-challenges"] input[name="position"]')
            for index in range(inputs.count()):
                inputs.nth(index).fill(str(inputs.count() - index))
            page.get_by_role('button', name='Guardar orden cronológico').click()
            page.wait_for_url('**/admin')
            assert page.locator('form[action="/admin/reorder-challenges"] label').first.inner_text().startswith('Prueba 12')
            page.get_by_role('button', name='Desbloquear la pantalla final', exact=True).click()
            page.wait_for_url('**/admin')
            page.get_by_role('link', name='Ver la pantalla final', exact=True).click()
            page.wait_for_url('**/final')
            assert page.locator('.podium-place').count() == 3
            assert page.locator('.podium-place-1 h3').inner_text() == 'Persona 1'
            assert page.locator('.winning-team h3').inner_text() == 'Verde'
            assert page.locator('.winning-team .score').inner_text() == '516 pts'
            page.emulate_media(reduced_motion='reduce')
            assert page.locator('.confetti').evaluate("node => getComputedStyle(node).display") == 'none'
            assert page.locator('.podium-place-1').evaluate("node => getComputedStyle(node).animationName") == 'none'
            for width in (320, 390, 1280):
                page.set_viewport_size({'width': width, 'height': 900})
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), f'Final overflow at {width}px'
            page.set_viewport_size({'width': 390, 'height': 844})
            page.screenshot(path='/tmp/mortezkana-final.png', full_page=True)
            page.goto(f'{base_url}/admin')
            page.get_by_role('button', name='Ocultar la pantalla final', exact=True).click()
            page.wait_for_url('**/admin')
            assert page.goto(f'{base_url}/final').status == 404
            assert not errors, errors
            browser.close()
        print('Browser checks passed: chart controls, public scoring guide, avatar uploads and display, chronology, final show/hide, reduced motion, and mobile/desktop layouts.')


if __name__ == '__main__':
    main()
