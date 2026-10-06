import sqlite3
import re
from contextlib import closing
import tempfile
import unittest
from pathlib import Path

from werkzeug.security import generate_password_hash

from mortezkana import create_app
from mortezkana.db import get_db, migrate
from mortezkana.domain import leaderboard, rank


class RankingTests(unittest.TestCase):
    def test_ties_share_rank_without_inventing_a_tiebreaker(self):
        entries = [{'id': 1, 'name': 'B', 'points': 8}, {'id': 2, 'name': 'A', 'points': 8},
                   {'id': 3, 'name': 'C', 'points': -2}]
        self.assertEqual([row['rank'] for row in rank(entries)], [1, 1, 3])

    def test_empty_ranking(self):
        self.assertEqual(list(rank([])), [])


class ApplicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password_hash = generate_password_hash('test-password', method='pbkdf2:sha256:1000')

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = {'TESTING': True, 'SECRET_KEY': 'test-key-' * 8,
                       'ADMIN_PASSWORD_HASH': self.password_hash,
                       'DATABASE': str(Path(self.directory.name) / 'competition.sqlite3')}
        self.app = create_app(self.config)
        self.client = self.app.test_client()
        with self.app.app_context():
            migrate()
            db = get_db()
            with db:
                db.executemany('INSERT INTO teams(name) VALUES (?)', [('Verde',), ('Azul',)])
                db.executemany('INSERT INTO participants(name, team_id) VALUES (?, ?)', [('Ana', 1), ('Luis', 2)])
                db.executemany('INSERT INTO challenges(name, kind, day) VALUES (?, ?, ?)',
                               [('Individual', 'individual', 1), ('Equipos', 'team', 2), ('Mixta', 'hybrid', 3)])

    def login(self):
        self.client.get('/admin/login')
        with self.client.session_transaction() as session:
            token = session['csrf']
        response = self.client.post('/admin/login', data={'csrf': token, 'password': 'test-password'})
        self.assertEqual(response.status_code, 302)
        self.client.get('/admin')

    def post(self, action, **data):
        with self.client.session_transaction() as session:
            token = session['csrf']
        return self.client.post('/admin/' + action, data={'csrf': token, **data})

    def test_public_pages_and_empty_states(self):
        for path in ('/', '/challenges', '/participants', '/admin/login'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'lang="es"', response.data)
            self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
        with self.app.app_context():
            with get_db() as db:
                db.execute('DELETE FROM participants')
                db.execute('DELETE FROM teams')
                db.execute('DELETE FROM challenges')
        self.assertIn('Todavía no hay participantes', self.client.get('/').text)
        self.assertIn('Todavía no hay pruebas', self.client.get('/challenges').text)

    def test_all_writes_require_admin(self):
        self.client.get('/admin/login')
        for action in ('teams', 'participants', 'challenges', 'status', 'results', 'corrections', 'logout',
                       'edit-teams', 'edit-participants', 'edit-challenges', 'assign-team'):
            self.assertEqual(self.post(action).status_code, 403)
        self.assertEqual(self.client.get('/admin/delete/participants/1').status_code, 403)
        self.assertEqual(self.post('delete/participants/1', stage='final').status_code, 403)

    def test_csrf_required_even_for_login_and_authenticated_writes(self):
        self.assertEqual(self.client.post('/admin/login', data={'password': 'test-password'}).status_code, 400)
        self.login()
        self.assertEqual(self.client.post('/admin/results').status_code, 400)

    def test_wrong_password_and_logout(self):
        self.client.get('/admin/login')
        self.assertEqual(self.post('login', password='wrong').status_code, 401)
        self.login()
        self.assertEqual(self.post('logout').status_code, 302)
        self.assertEqual(self.client.get('/admin').status_code, 302)

    def test_team_and_participant_capacity_are_database_constraints(self):
        with self.app.app_context():
            db = get_db()
            with self.assertRaises(sqlite3.IntegrityError), db:
                db.execute("INSERT INTO teams(name) VALUES ('Tercero')")
            with db:
                db.executemany('INSERT INTO participants(name, team_id) VALUES (?, 1)', [(str(i),) for i in range(4)])
            with self.assertRaises(sqlite3.IntegrityError), db:
                db.execute("INSERT INTO participants(name, team_id) VALUES ('Sexto', 1)")
            with self.assertRaises(sqlite3.IntegrityError), db:
                db.execute('UPDATE participants SET team_id=1 WHERE id=2')

    def test_results_duplicates_and_corrections(self):
        self.login()
        values = {'challenge_id': 1, 'target': 'participant:1', 'points': 10, 'notes': 'Resultado validado'}
        self.assertEqual(self.post('results', **values).status_code, 302)
        self.post('results', **values)
        with self.app.app_context():
            db = get_db()
            self.assertEqual(db.execute('SELECT COUNT(*) FROM results').fetchone()[0], 1)
            self.assertEqual(leaderboard(db, 'participant')[0]['points'], 10)
            self.assertEqual(leaderboard(db, 'team')[0]['points'], 10)
        self.assertEqual(self.post('corrections', result_id=1, revision=1, points=-3, notes='Corrección').status_code, 302)
        # A second device cannot overwrite a newer correction with a stale form.
        self.assertEqual(self.post('corrections', result_id=1, revision=1, points=99, notes='Antigua').status_code, 409)
        with self.app.app_context():
            result = get_db().execute('SELECT * FROM results').fetchone()
            self.assertEqual(result['points'], -3)
            self.assertEqual(result['revision'], 2)

    def test_hybrid_scores_include_members_and_direct_awards_once(self):
        self.login()
        self.post('results', challenge_id=3, target='participant:1', points=8, notes='Individual')
        self.post('results', challenge_id=3, target='team:1', points=4, notes='Equipo')
        with self.app.app_context():
            self.assertEqual(leaderboard(get_db(), 'participant')[0]['points'], 8)
            self.assertEqual(leaderboard(get_db(), 'team')[0]['points'], 12)

    def test_invalid_results_do_not_persist(self):
        self.login()
        for values in [dict(challenge_id=1, target='team:1', points=4),
                       dict(challenge_id=2, target='participant:1', points=4),
                       dict(challenge_id=999, target='team:1', points=4),
                       dict(challenge_id=1, target='participant:999', points=4),
                       dict(challenge_id=1, target='participant:1', points='1.5'),
                       dict(challenge_id=1, target='participant:1', points=1000001),
                       dict(challenge_id=1, target='bad', points=4)]:
            self.post('results', **values, notes='Inválido')
        with self.app.app_context():
            self.assertEqual(get_db().execute('SELECT COUNT(*) FROM results').fetchone()[0], 0)

    def test_challenge_creation_and_status_validation(self):
        self.login()
        self.post('challenges', name='Nueva', kind='hybrid', day=2, description='Reglas pendientes')
        self.post('status', challenge_id=4, status='active')
        self.post('status', challenge_id=4, status='invented')
        with self.app.app_context():
            self.assertEqual(get_db().execute('SELECT status FROM challenges WHERE id=4').fetchone()[0], 'active')
        self.assertEqual(self.post('status', challenge_id=999, status='active').status_code, 404)

    def test_persistence_and_migrations_are_non_destructive(self):
        self.login()
        self.post('results', challenge_id=1, target='participant:1', points=12, notes='Persistencia')
        restarted = create_app(self.config)
        with restarted.app_context():
            migrate()
            migrate()
            self.assertEqual(leaderboard(get_db(), 'participant')[0]['points'], 12)
            self.assertEqual(get_db().execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0], 2)

    def test_setup_cli_applies_migrations_in_application_context(self):
        runner = self.app.test_cli_runner()
        result = runner.invoke(args=['init-db'])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn('Database migrations applied.', result.output)

    def test_user_input_is_escaped(self):
        self.login()
        self.post('participants', name='<script>alert(1)</script>', team_id=1)
        self.assertNotIn(b'<script>', self.client.get('/participants').data)
        self.assertIn(b'&lt;script&gt;', self.client.get('/participants').data)

    def test_transaction_rolls_back_on_failure(self):
        with self.app.app_context():
            db = get_db()
            with self.assertRaises(sqlite3.IntegrityError), db:
                db.execute("INSERT INTO results(challenge_id, participant_id, points) VALUES (1, 1, 5)")
                db.execute("INSERT INTO results(challenge_id, participant_id, points) VALUES (1, 999, 5)")
            self.assertEqual(db.execute('SELECT COUNT(*) FROM results').fetchone()[0], 0)

    def deletion_review(self, kind, entity_id):
        path = f'delete/{kind}/{entity_id}'
        response = self.client.get('/admin/' + path)
        self.assertEqual(response.status_code, 200)
        fingerprint = re.search(r'name="fingerprint" value="([a-f0-9]+)"', response.text).group(1)
        response = self.post(path, stage='review', acknowledge='yes', fingerprint=fingerprint)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Confirmación 2 de 2', response.text)
        with self.client.session_transaction() as session:
            return session['deletion']['ticket']

    def delete_confirmed(self, kind, entity_id):
        ticket = self.deletion_review(kind, entity_id)
        response = self.post(f'delete/{kind}/{entity_id}', stage='final', ticket=ticket, confirmation='ELIMINAR')
        self.assertEqual(response.status_code, 302)

    def seed_awards(self):
        self.post('results', challenge_id=1, target='participant:1', points=10, notes='Individual')
        self.post('results', challenge_id=2, target='team:1', points=6, notes='Equipo')
        self.post('results', challenge_id=3, target='participant:1', points=-2, notes='Mixta individual')
        self.post('results', challenge_id=3, target='team:1', points=4, notes='Mixta equipo')

    def test_people_can_be_created_before_teams_and_assigned_later(self):
        self.login()
        with self.app.app_context(), get_db() as db:
            db.execute('DELETE FROM teams')
        self.post('participants', name='Nueva')
        with self.app.app_context():
            person = get_db().execute("SELECT * FROM participants WHERE name='Nueva'").fetchone()
            self.assertIsNone(person['team_id'])
            person_id = person['id']
        self.assertIn('Nueva', self.client.get('/participants').text)
        self.assertIn('Sin equipo', self.client.get('/participants').text)
        self.post('teams', name='Nuevo equipo')
        with self.app.app_context():
            team_id = get_db().execute('SELECT id FROM teams').fetchone()[0]
        self.post('assign-team', participant_id=person_id, team_id=team_id)
        with self.app.app_context():
            self.assertEqual(get_db().execute('SELECT team_id FROM participants WHERE id=?', (person_id,)).fetchone()[0], team_id)

    def test_unassigned_people_still_count_toward_ten_person_limit(self):
        self.login()
        for index in range(9):
            self.post('participants', name=f'Persona {index}')
        with self.app.app_context():
            self.assertEqual(get_db().execute('SELECT COUNT(*) FROM participants').fetchone()[0], 10)

    def test_edit_people_teams_and_challenges_preserves_results(self):
        self.login()
        self.seed_awards()
        self.post('edit-participants', participant_id=1, name='Ana corregida')
        self.post('edit-teams', team_id=1, name='Verde corregido')
        self.post('edit-challenges', challenge_id=1, name='Prueba corregida', description='Nuevas reglas', kind='hybrid', day=3)
        with self.app.app_context():
            db = get_db()
            self.assertEqual(db.execute('SELECT name FROM participants WHERE id=1').fetchone()[0], 'Ana corregida')
            self.assertEqual(db.execute('SELECT name FROM teams WHERE id=1').fetchone()[0], 'Verde corregido')
            challenge = db.execute('SELECT * FROM challenges WHERE id=1').fetchone()
            self.assertEqual((challenge['name'], challenge['kind'], challenge['day']), ('Prueba corregida', 'hybrid', 3))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM results').fetchone()[0], 4)
        for action, fields in [('edit-participants', {'participant_id': 999, 'name': 'Otro'}),
                               ('edit-teams', {'team_id': 999, 'name': 'Otro'}),
                               ('edit-challenges', {'challenge_id': 999, 'name': 'Otro', 'kind': 'team', 'day': 1})]:
            self.assertEqual(self.post(action, **fields).status_code, 404)

    def test_incompatible_challenge_edit_rolls_back_all_fields(self):
        self.login()
        self.seed_awards()
        self.post('edit-challenges', challenge_id=3, name='Cambio inválido', kind='individual', day=1)
        with self.app.app_context():
            challenge = get_db().execute('SELECT * FROM challenges WHERE id=3').fetchone()
            self.assertEqual((challenge['name'], challenge['kind'], challenge['day']), ('Mixta', 'hybrid', 3))

    def test_team_transfer_and_unassignment_recalculate_scores(self):
        self.login()
        self.seed_awards()
        self.post('assign-team', participant_id=1, team_id=2)
        with self.app.app_context():
            scores = {row['id']: row['points'] for row in leaderboard(get_db(), 'team')}
            self.assertEqual(scores, {1: 10, 2: 8})
            self.assertEqual(leaderboard(get_db(), 'participant')[0]['points'], 8)
        self.post('assign-team', participant_id=1, team_id='')
        with self.app.app_context():
            scores = {row['id']: row['points'] for row in leaderboard(get_db(), 'team')}
            self.assertEqual(scores, {1: 10, 2: 0})
            self.assertEqual(leaderboard(get_db(), 'participant')[0]['points'], 8)

    def test_assignment_from_unassigned_to_full_team_is_rejected(self):
        self.login()
        with self.app.app_context(), get_db() as db:
            db.executemany('INSERT INTO participants(name, team_id) VALUES (?, 1)', [(str(index),) for index in range(4)])
            db.execute("INSERT INTO participants(name) VALUES ('Sin equipo')")
            person_id = db.execute("SELECT id FROM participants WHERE name='Sin equipo'").fetchone()[0]
        self.post('assign-team', participant_id=person_id, team_id=1)
        self.post('assign-team', participant_id=2, team_id=1)
        self.post('assign-team', participant_id=person_id, team_id=999)
        with self.app.app_context():
            self.assertIsNone(get_db().execute('SELECT team_id FROM participants WHERE id=?', (person_id,)).fetchone()[0])
            self.assertEqual(get_db().execute('SELECT team_id FROM participants WHERE id=2').fetchone()[0], 2)

    def test_deletion_cannot_skip_either_confirmation(self):
        self.login()
        path = 'delete/participants/1'
        self.assertEqual(self.post(path, stage='final', ticket='fake', confirmation='ELIMINAR').status_code, 400)
        self.assertEqual(self.post(path, stage='review', acknowledge='no').status_code, 400)
        ticket = self.deletion_review('participants', 1)
        self.assertEqual(self.post(path, stage='final', ticket=ticket, confirmation='no').status_code, 400)
        self.assertEqual(self.post(path, stage='final', ticket='fake', confirmation='ELIMINAR').status_code, 400)
        self.assertEqual(self.post('delete/participants/2', stage='final', ticket=ticket, confirmation='ELIMINAR').status_code, 400)
        with self.app.app_context():
            self.assertEqual(get_db().execute('SELECT COUNT(*) FROM participants').fetchone()[0], 2)

    def test_delete_person_removes_only_their_awards(self):
        self.login()
        self.seed_awards()
        self.delete_confirmed('participants', 1)
        with self.app.app_context():
            db = get_db()
            self.assertIsNone(db.execute('SELECT * FROM participants WHERE id=1').fetchone())
            self.assertEqual(db.execute('SELECT COUNT(*) FROM results').fetchone()[0], 2)
            self.assertEqual(leaderboard(db, 'team')[0]['points'], 10)

    def test_delete_team_unassigns_people_and_removes_direct_awards(self):
        self.login()
        self.seed_awards()
        self.delete_confirmed('teams', 1)
        with self.app.app_context():
            db = get_db()
            self.assertIsNone(db.execute('SELECT team_id FROM participants WHERE id=1').fetchone()[0])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM results').fetchone()[0], 2)
            self.assertEqual(leaderboard(db, 'participant')[0]['points'], 8)
            self.assertEqual(leaderboard(db, 'team')[0]['points'], 0)
        self.post('teams', name='Recreado')
        with self.app.app_context():
            team_id = get_db().execute("SELECT id FROM teams WHERE name='Recreado'").fetchone()[0]
        self.post('assign-team', participant_id=1, team_id=team_id)
        with self.app.app_context():
            self.assertEqual(leaderboard(get_db(), 'team')[0]['points'], 8)

    def test_delete_challenge_removes_individual_and_team_awards(self):
        self.login()
        self.seed_awards()
        self.delete_confirmed('challenges', 3)
        with self.app.app_context():
            db = get_db()
            self.assertIsNone(db.execute('SELECT * FROM challenges WHERE id=3').fetchone())
            self.assertEqual(db.execute('SELECT COUNT(*) FROM results').fetchone()[0], 2)
            self.assertEqual(leaderboard(db, 'participant')[0]['points'], 10)
            self.assertEqual(leaderboard(db, 'team')[0]['points'], 16)

    def test_deletion_requires_csrf_and_unexpired_confirmation(self):
        self.login()
        ticket = self.deletion_review('participants', 1)
        path = '/admin/delete/participants/1'
        self.assertEqual(self.client.post(path, data={'stage': 'final', 'ticket': ticket, 'confirmation': 'ELIMINAR'}).status_code, 400)
        with self.client.session_transaction() as session:
            pending = dict(session['deletion'])
            pending['expires'] = 0
            session['deletion'] = pending
        self.assertEqual(self.post('delete/participants/1', stage='final', ticket=ticket, confirmation='ELIMINAR').status_code, 400)

    def test_deletion_rechecks_changes_between_confirmations(self):
        self.login()
        ticket = self.deletion_review('participants', 1)
        self.post('results', challenge_id=1, target='participant:1', points=7, notes='Resultado nuevo')
        response = self.post('delete/participants/1', stage='final', ticket=ticket, confirmation='ELIMINAR')
        self.assertEqual(response.status_code, 409)
        with self.app.app_context():
            self.assertEqual(get_db().execute('SELECT COUNT(*) FROM participants').fetchone()[0], 2)
            self.assertEqual(get_db().execute('SELECT COUNT(*) FROM results').fetchone()[0], 1)

    def test_completed_challenges_show_summaries_and_grouped_corrections(self):
        self.login()
        self.seed_awards()
        self.assertNotIn('Resumen de puntuaciones', self.client.get('/challenges').text)
        self.post('status', challenge_id=3, status='completed')
        public = self.client.get('/challenges').text
        self.assertIn('Resumen de puntuaciones', public)
        self.assertIn('Puntuaciones individuales', public)
        self.assertIn('Puntuaciones de equipos', public)
        self.assertIn('Ana', public)
        self.assertIn('Verde', public)
        self.assertIn('>-2</td>', public)
        admin = self.client.get('/admin').text
        self.assertEqual(admin.count('class="card padded result-group"'), 3)
        self.assertIn('Mixta · 2 resultados · Finalizada', admin)
        self.post('corrections', result_id=3, revision=1, points=9, notes='Corregido')
        self.assertIn('>9</td>', self.client.get('/challenges').text)
        self.post('status', challenge_id=1, status='completed')
        self.delete_confirmed('participants', 1)
        self.assertIn('Esta prueba ha finalizado sin puntuaciones registradas.', self.client.get('/challenges').text)

    def test_migration_preserves_existing_roster_and_results(self):
        database = str(Path(self.directory.name) / 'old.sqlite3')
        schema = Path(__file__).resolve().parents[1] / 'mortezkana/migrations/001_initial.sql'
        with closing(sqlite3.connect(database)) as db, db:
            db.execute('PRAGMA foreign_keys = ON')
            db.executescript(schema.read_text())
            db.execute('CREATE TABLE schema_migrations (version TEXT PRIMARY KEY)')
            db.execute("INSERT INTO schema_migrations VALUES ('001_initial.sql')")
            db.execute("INSERT INTO teams(id, name) VALUES (4, 'Original')")
            db.execute("INSERT INTO participants(id, name, team_id) VALUES (7, 'Persona original', 4)")
            db.execute("INSERT INTO challenges(id, name, kind, day) VALUES (9, 'Prueba original', 'hybrid', 2)")
            db.execute("INSERT INTO results(id, challenge_id, participant_id, points, notes, revision) VALUES (11, 9, 7, 8, 'Original', 3)")
            db.execute("INSERT INTO results(id, challenge_id, team_id, points, notes) VALUES (12, 9, 4, -2, 'Equipo')")
            before = db.execute('SELECT * FROM results ORDER BY id').fetchall()
        upgraded = create_app({**self.config, 'DATABASE': database})
        with upgraded.app_context():
            migrate()
            migrate()
            db = get_db()
            self.assertEqual([tuple(row) for row in db.execute('SELECT * FROM results ORDER BY id')], before)
            self.assertEqual(db.execute('SELECT team_id FROM participants WHERE id=7').fetchone()[0], 4)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(leaderboard(db, 'team')[0]['points'], 6)
            with db:
                db.execute("INSERT INTO participants(name) VALUES ('Nueva sin equipo')")
            self.assertEqual(db.execute('SELECT COUNT(*) FROM participants').fetchone()[0], 2)


if __name__ == '__main__':
    unittest.main()
