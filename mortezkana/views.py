from functools import wraps
from io import BytesIO
import hashlib
import json
import secrets
import sqlite3
import time

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash

from .db import get_db
from .avatars import AVATAR_TABLES, normalize_avatar
from .domain import (INDIVIDUAL_POINTS, HYBRID_TEAM_POINTS, HYBRID_INDIVIDUAL_POINTS, TEAM_MEMBER_POINTS,
                     challenge_results, chronology_fingerprint, compact_chronology,
                     leaderboard, reorder_challenges, score_history)
from .rounds import rounds_by_challenge, save_round

bp = Blueprint('web', __name__)
LABELS = {'individual': 'Individual', 'team': 'Por equipos', 'hybrid': 'Mixta',
          'pending': 'Pendiente', 'active': 'En juego', 'completed': 'Finalizada'}


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('admin'):
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def csrf_token():
    if 'csrf' not in session:
        session['csrf'] = secrets.token_hex(32)
    return session['csrf']


@bp.app_context_processor
def template_helpers():
    unlocked = get_db().execute('SELECT finale_unlocked FROM competition_settings WHERE id=1').fetchone()[0]
    return {'csrf_token': csrf_token, 'labels': LABELS, 'finale_unlocked': bool(unlocked),
            'individual_points': INDIVIDUAL_POINTS, 'hybrid_team_points': HYBRID_TEAM_POINTS,
            'hybrid_individual_points': HYBRID_INDIVIDUAL_POINTS, 'team_member_points': TEAM_MEMBER_POINTS}


@bp.before_app_request
def protect_forms():
    if request.method == 'POST':
        expected = session.get('csrf')
        received = request.form.get('csrf', '')
        if not expected or not secrets.compare_digest(expected, received):
            abort(400)


def text_field(name, maximum=80):
    value = request.form.get(name, '').strip()
    if not value or len(value) > maximum:
        raise ValueError('Revisa los campos: faltan datos o son demasiado largos.')
    return value


def integer_field(name, minimum=1, maximum=1000000):
    try:
        value = int(request.form.get(name, ''))
    except ValueError:
        raise ValueError('Introduce un número entero válido.') from None
    if not minimum <= value <= maximum:
        raise ValueError('El número está fuera del intervalo permitido.')
    return value


def option_field(name, options):
    value = request.form.get(name)
    if value not in options:
        raise ValueError('Selecciona una opción válida.')
    return value


@bp.get('/')
def index():
    db = get_db()
    return render_template('index.html', individuals=leaderboard(db, 'participant'),
                           teams=leaderboard(db, 'team'), history=score_history(db))


@bp.get('/final')
def finale():
    db = get_db()
    if not db.execute('SELECT finale_unlocked FROM competition_settings WHERE id=1').fetchone()[0]:
        abort(404)
    individuals = leaderboard(db, 'participant')
    teams = leaderboard(db, 'team')
    podium = [{'rank': position, 'people': [person for person in individuals if person['rank'] == position]}
              for position in (2, 1, 3) if any(person['rank'] == position for person in individuals)]
    return render_template('finale.html', individuals=individuals, teams=teams, podium=podium,
                           winning_teams=[team for team in teams if team['rank'] == 1])


@bp.get('/challenges')
def challenges():
    db = get_db()
    rows = db.execute('SELECT * FROM challenges ORDER BY chronology_position, id').fetchall()
    return render_template('challenges.html', challenges=rows, results_by_challenge=challenge_results(db),
                           rounds_by_challenge=rounds_by_challenge(db))


@bp.get('/participants')
def participants():
    db = get_db()
    rows = db.execute('SELECT id, name, team_id, (avatar IS NOT NULL) AS has_avatar FROM participants ORDER BY name, id').fetchall()
    teams = db.execute('SELECT id, name, (avatar IS NOT NULL) AS has_avatar FROM teams ORDER BY id').fetchall()
    return render_template('participants.html', participants=rows, teams=teams)


@bp.get('/avatars/<kind>/<int:entity_id>')
def avatar(kind, entity_id):
    if kind not in AVATAR_TABLES:
        abort(404)
    row = get_db().execute(f'SELECT avatar FROM {AVATAR_TABLES[kind]} WHERE id=?', (entity_id,)).fetchone()
    if row is None:
        abort(404)
    if row['avatar'] is None:
        return redirect(url_for('static', filename='avatar-team.svg' if kind == 'teams' else 'avatar-person.svg'))
    return send_file(BytesIO(row['avatar']), mimetype='image/jpeg', download_name='avatar.jpg', max_age=0)


@bp.post('/admin/avatars/<kind>/<int:entity_id>')
@admin_required
def change_avatar(kind, entity_id):
    if kind not in AVATAR_TABLES:
        abort(404)
    db = get_db()
    if db.execute(f'SELECT id FROM {AVATAR_TABLES[kind]} WHERE id=?', (entity_id,)).fetchone() is None:
        abort(404)
    try:
        action = option_field('action', ('upload', 'default'))
        photo = normalize_avatar(request.files.get('photo')) if action == 'upload' else None
        with db:
            require_updated(db.execute(f'UPDATE {AVATAR_TABLES[kind]} SET avatar=? WHERE id=?', (photo, entity_id)))
    except ValueError as error:
        flash(str(error), 'error')
    else:
        flash('Avatar guardado.' if action == 'upload' else 'Avatar predeterminado restaurado.', 'success')
    return redirect(url_for('web.admin'))


@bp.route('/admin/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if check_password_hash(current_app.config['ADMIN_PASSWORD_HASH'], request.form.get('password', '')):
            session.clear()
            session['admin'] = True
            session.permanent = True
            return redirect(url_for('web.admin'))
        flash('La contraseña no es correcta.', 'error')
        return render_template('login.html'), 401
    return render_template('login.html')


@bp.post('/admin/logout')
@admin_required
def logout():
    session.clear()
    return redirect(url_for('web.index'))


@bp.get('/admin')
def admin():
    if not session.get('admin'):
        return redirect(url_for('web.login'))
    db = get_db()
    session.setdefault('round_submission', secrets.token_hex(32))
    challenges = db.execute('SELECT * FROM challenges ORDER BY chronology_position, id').fetchall()
    return render_template('admin.html',
        teams=db.execute('SELECT id, name, (avatar IS NOT NULL) AS has_avatar FROM teams ORDER BY id').fetchall(),
        participants=db.execute('SELECT id, name, team_id, (avatar IS NOT NULL) AS has_avatar FROM participants ORDER BY id').fetchall(),
        challenges=challenges, chronology_fingerprint=chronology_fingerprint(challenges),
        results_by_challenge=challenge_results(db), rounds_by_challenge=rounds_by_challenge(db),
        round_submission=session['round_submission'])


def require_updated(cursor):
    if cursor.rowcount != 1:
        abort(404)


def challenge_fields():
    description = request.form.get('description', '').strip()
    if len(description) > 2000:
        raise ValueError('La descripción es demasiado larga.')
    return (text_field('name'), description,
            option_field('kind', ('individual', 'team', 'hybrid')), integer_field('day', 1, 3))


@bp.post('/admin/<action>')
@admin_required
def mutate(action):
    db = get_db()
    try:
        with db:
            if action == 'teams':
                db.execute('INSERT INTO teams(name) VALUES (?)', (text_field('name'),))
            elif action == 'participants':
                db.execute('INSERT INTO participants(name) VALUES (?)', (text_field('name'),))
            elif action == 'edit-teams':
                require_updated(db.execute('UPDATE teams SET name=? WHERE id=?', (text_field('name'), integer_field('team_id'))))
            elif action == 'edit-participants':
                require_updated(db.execute('UPDATE participants SET name=? WHERE id=?', (text_field('name'), integer_field('participant_id'))))
            elif action == 'assign-team':
                team_id = integer_field('team_id') if request.form.get('team_id', '') else None
                require_updated(db.execute('UPDATE participants SET team_id=? WHERE id=?', (team_id, integer_field('participant_id'))))
            elif action == 'challenges':
                fields = challenge_fields()
                db.execute('BEGIN IMMEDIATE')
                position = db.execute('SELECT COALESCE(MAX(chronology_position), 0) + 1 FROM challenges').fetchone()[0]
                db.execute('INSERT INTO challenges(name, description, kind, day, chronology_position) VALUES (?, ?, ?, ?, ?)',
                    (*fields, position))
            elif action == 'reorder-challenges':
                try:
                    identities = [int(value) for value in request.form.getlist('challenge_id')]
                    positions = [int(value) for value in request.form.getlist('position')]
                except ValueError:
                    raise ValueError('Introduce posiciones enteras válidas para las pruebas.') from None
                db.execute('BEGIN IMMEDIATE')
                if not reorder_challenges(db, identities, positions, request.form.get('fingerprint')):
                    abort(409)
            elif action == 'finale':
                state = option_field('state', ('unlock', 'lock'))
                db.execute('UPDATE competition_settings SET finale_unlocked=? WHERE id=1', (int(state == 'unlock'),))
            elif action == 'edit-challenges':
                require_updated(db.execute('UPDATE challenges SET name=?, description=?, kind=?, day=? WHERE id=?',
                    (*challenge_fields(), integer_field('challenge_id'))))
            elif action == 'status':
                cursor = db.execute('UPDATE challenges SET status=? WHERE id=?',
                    (option_field('status', ('pending', 'active', 'completed')), integer_field('challenge_id')))
                if cursor.rowcount != 1:
                    abort(404)
            elif action == 'results':
                target = text_field('target')
                try:
                    kind, target_id = target.split(':')
                    target_id = int(target_id)
                except ValueError:
                    raise ValueError('Selecciona un participante o equipo válido.') from None
                if kind not in ('participant', 'team') or target_id <= 0:
                    raise ValueError('Selecciona un participante o equipo válido.')
                award_kind = request.form.get('award_kind', 'standard')
                if award_kind not in ('standard', 'extraordinary'):
                    raise ValueError('Selecciona un tipo de puntuación válido.')
                db.execute('INSERT INTO results(challenge_id, participant_id, team_id, points, notes, award_kind) VALUES (?, ?, ?, ?, ?, ?)',
                    (integer_field('challenge_id'), target_id if kind == 'participant' else None,
                     target_id if kind == 'team' else None, integer_field('points', -1000000), text_field('notes', 500), award_kind))
            elif action == 'corrections':
                cursor = db.execute("""UPDATE results SET points=?, notes=?, revision=revision+1,
                    updated_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id=? AND revision=?""",
                    (integer_field('points', -1000000), text_field('notes', 500), integer_field('result_id'), integer_field('revision')))
                if cursor.rowcount != 1:
                    abort(409)
            elif action in ('rounds', 'edit-rounds'):
                db.execute('BEGIN IMMEDIATE')
                previous = None
                if action == 'edit-rounds':
                    previous = db.execute('SELECT * FROM rounds WHERE id=?', (integer_field('round_id'),)).fetchone()
                    if previous is None:
                        abort(404)
                else:
                    expected = session.get('round_submission')
                    if not expected or request.form.get('submission_key') != expected:
                        abort(409)
                    if db.execute('SELECT 1 FROM rounds WHERE submission_key=?', (expected,)).fetchone():
                        abort(409)
                save_round(db, request.form, (integer_field('round_number', 1, 999), text_field('format'), text_field('outcome', 1000)), previous)
            else:
                abort(404)
    except ValueError as error:
        flash(str(error), 'error')
    except sqlite3.IntegrityError:
        flash('No se pudo guardar: revisa los límites, las personas y equipos seleccionados o si el resultado ya existe. Las puntuaciones extraordinarias son individuales y solo se admiten en pruebas por equipos. No puedes cambiar el tipo de una prueba si sus resultados son incompatibles.', 'error')
    else:
        if action == 'rounds':
            session['round_submission'] = secrets.token_hex(32)
        if action == 'finale':
            flash('Pantalla final oculta.' if state == 'lock' else 'Pantalla final publicada.', 'success')
        else:
            flash('Cambios guardados.', 'success')
    return redirect(url_for('web.admin'))


DELETE_TARGETS = {
    'participants': ('participants', 'participant_id', 'persona'),
    'teams': ('teams', 'team_id', 'equipo'),
    'challenges': ('challenges', 'challenge_id', 'prueba'),
}


def deletion_snapshot(db, kind, entity_id):
    table, result_column, label = DELETE_TARGETS[kind]
    # Table/column identifiers come exclusively from the fixed allowlist above.
    entity = db.execute(f'SELECT * FROM {table} WHERE id=?', (entity_id,)).fetchone()
    if entity is None:
        abort(404)
    results = db.execute(f'SELECT * FROM results WHERE {result_column}=? ORDER BY id', (entity_id,)).fetchall()
    members = db.execute('SELECT * FROM participants WHERE team_id=? ORDER BY id', (entity_id,)).fetchall() if kind == 'teams' else []
    def serializable(row):
        values = dict(row)
        if values.get('avatar') is not None:
            values['avatar'] = hashlib.sha256(values['avatar']).hexdigest()
        return values
    data = {'entity': serializable(entity), 'results': [dict(row) for row in results],
            'members': [serializable(row) for row in members]}
    rounds = db.execute('SELECT * FROM rounds WHERE challenge_id=? ORDER BY id', (entity_id,)).fetchall() if kind == 'challenges' else []
    data['rounds'] = [dict(row) for row in rounds]
    if kind == 'challenges':
        data['round_people'] = [dict(row) for row in db.execute('SELECT rp.* FROM round_people rp JOIN rounds r ON r.id=rp.round_id WHERE r.challenge_id=? ORDER BY rp.id', (entity_id,))]
    fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    return {'entity': entity, 'label': label, 'result_count': len(results),
            'member_count': len(members), 'round_count': len(rounds), 'fingerprint': fingerprint}


@bp.route('/admin/delete/<kind>/<int:entity_id>', methods=['GET', 'POST'])
@admin_required
def delete_entity(kind, entity_id):
    if kind not in DELETE_TARGETS:
        abort(404)
    db = get_db()
    with db:
        # Keep the final snapshot and cascade deletion atomic across devices.
        if request.method == 'POST':
            db.execute('BEGIN IMMEDIATE')
        snapshot = deletion_snapshot(db, kind, entity_id)
        if request.method == 'GET':
            return render_template('delete.html', kind=kind, stage='review', **snapshot)
        if request.form.get('stage') == 'review':
            if request.form.get('acknowledge') != 'yes':
                abort(400)
            if request.form.get('fingerprint') != snapshot['fingerprint']:
                abort(409)
            ticket = secrets.token_hex(32)
            session['deletion'] = {'kind': kind, 'id': entity_id, 'ticket': ticket,
                                   'fingerprint': snapshot['fingerprint'], 'expires': time.time() + 600}
            return render_template('delete.html', kind=kind, stage='final', ticket=ticket, **snapshot)
        pending = session.get('deletion', {})
        if (request.form.get('stage') != 'final' or pending.get('kind') != kind
                or pending.get('id') != entity_id or pending.get('expires', 0) < time.time()
                or not secrets.compare_digest(pending.get('ticket', ''), request.form.get('ticket', ''))
                or not pending.get('ticket') or request.form.get('confirmation') != 'ELIMINAR'):
            abort(400)
        if pending['fingerprint'] != snapshot['fingerprint']:
            abort(409)
        table = DELETE_TARGETS[kind][0]
        db.execute(f'DELETE FROM {table} WHERE id=?', (entity_id,))
        if kind == 'challenges':
            compact_chronology(db)
    session.pop('deletion', None)
    flash('Eliminación completada. La clasificación se ha actualizado.', 'success')
    return redirect(url_for('web.admin'))
