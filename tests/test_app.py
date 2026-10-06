import sqlite3
import re
from contextlib import closing
from io import BytesIO
import tempfile
import unittest
from pathlib import Path

from werkzeug.security import generate_password_hash
from PIL import Image

from mortezkana import create_app
from mortezkana.db import get_db, migrate
from mortezkana.domain import leaderboard, rank, score_history


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
                db.executemany('INSERT INTO challenges(name, kind, day, chronology_position) VALUES (?, ?, ?, ?)',
                               [('Individual', 'individual', 1, 1), ('Equipos', 'team', 2, 2), ('Mixta', 'hybrid', 3, 3)])

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
                       'edit-teams', 'edit-participants', 'edit-challenges', 'assign-team', 'rounds', 'edit-rounds',
                       'reorder-challenges', 'finale'):
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
            self.assertEqual(get_db().execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0], 5)

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
            self.assertEqual([tuple(row)[:-1] for row in db.execute('SELECT * FROM results ORDER BY id')], before)
            self.assertEqual([row[0] for row in db.execute('SELECT award_kind FROM results')], ['standard', 'standard'])
            self.assertEqual(db.execute('SELECT team_id FROM participants WHERE id=7').fetchone()[0], 4)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(leaderboard(db, 'team')[0]['points'], 6)
            with db:
                db.execute("INSERT INTO participants(name) VALUES ('Nueva sin equipo')")
            self.assertEqual(db.execute('SELECT COUNT(*) FROM participants').fetchone()[0], 2)

    def round_data(self, **overrides):
        with self.client.session_transaction() as session:
            key = session['round_submission']
        return {'challenge_id': 1, 'round_number': 1, 'format': '1vs1',
                'left_people': ['1'], 'right_people': ['2'], 'outcome': 'Ana gana 3–1',
                'submission_key': key, **overrides}

    def test_summary_shows_notes_and_corrected_notes_safely(self):
        self.login()
        self.post('results', challenge_id=1, target='participant:1', points=10,
                  notes='Acertó dos tiros <script>alert(1)</script>')
        self.post('status', challenge_id=1, status='completed')
        public = self.client.get('/challenges').text
        self.assertIn('Resultado o motivo:', public)
        self.assertIn('Acertó dos tiros &lt;script&gt;', public)
        self.assertNotIn('<script>', public)
        self.post('corrections', result_id=1, revision=1, points=8, notes='Resultado revisado')
        self.assertIn('Resultado revisado', self.client.get('/challenges').text)
        self.assertIn('Resultado revisado', self.client.get('/admin').text)

    def test_admin_scoring_reference_is_complete(self):
        self.login()
        page = self.client.get('/admin').text
        self.assertIn('Chuleta de puntuaciones', page)
        for position, points in enumerate((10, 8, 6, 5, 4, 3, 2, 2, 1, 1), 1):
            self.assertIn(f'<th scope="row">{position}.º</th><td class="number">{points} pts</td>', page)
        for award in ('+3 pts', '+1 pts', '+7 pts a cada persona', '+3 pts a cada persona'):
            self.assertIn(award, page)
        self.assertIn('MVP', page)
        public = self.app.test_client().get('/challenges').text
        self.assertIn('Chuleta de puntuaciones', public)
        self.assertIn('Victoria individual: <strong>+3 puntos</strong>', public)
        self.assertIn('Derrota: <strong>+1 punto</strong>', public)

    def test_team_challenges_allow_regular_and_extraordinary_individual_awards(self):
        self.login()
        self.post('results', challenge_id=2, target='participant:1', points=7, notes='Equipo ganador')
        self.post('results', challenge_id=2, target='participant:2', points=3, notes='Equipo perdedor')
        values = dict(challenge_id=2, target='participant:1', points=2, notes='MVP', award_kind='extraordinary')
        self.post('results', **values)
        self.post('results', **values)
        with self.app.app_context():
            db = get_db()
            self.assertEqual(db.execute('SELECT COUNT(*) FROM results').fetchone()[0], 3)
            self.assertEqual({row['id']: row['points'] for row in leaderboard(db, 'participant')}, {1: 9, 2: 3})
            self.assertEqual({row['id']: row['points'] for row in leaderboard(db, 'team')}, {1: 9, 2: 3})
            extra_id = db.execute("SELECT id FROM results WHERE award_kind='extraordinary'").fetchone()[0]
        self.post('status', challenge_id=2, status='completed')
        public = self.client.get('/challenges').text
        self.assertIn('MVP', public)
        self.assertIn('Extraordinaria', public)
        self.post('corrections', result_id=extra_id, revision=1, points=4, notes='MVP corregido')
        self.post('assign-team', participant_id=1, team_id=2)
        with self.app.app_context():
            self.assertEqual({row['id']: row['points'] for row in leaderboard(get_db(), 'team')}, {1: 0, 2: 14})

    def test_extraordinary_awards_require_person_and_team_challenge(self):
        self.login()
        for challenge, target, kind in [(1, 'participant:1', 'extraordinary'),
                                        (3, 'participant:1', 'extraordinary'),
                                        (2, 'team:1', 'extraordinary'),
                                        (2, 'participant:1', 'invalid')]:
            self.post('results', challenge_id=challenge, target=target, award_kind=kind, points=2, notes='Inválido')
        with self.app.app_context():
            self.assertEqual(get_db().execute('SELECT COUNT(*) FROM results').fetchone()[0], 0)

    def test_extraordinary_award_blocks_incompatible_challenge_type_edit(self):
        self.login()
        self.post('results', challenge_id=2, target='participant:1', award_kind='extraordinary', points=2, notes='MVP')
        self.post('edit-challenges', challenge_id=2, name='Equipos', kind='hybrid', day=2)
        with self.app.app_context():
            self.assertEqual(get_db().execute('SELECT kind FROM challenges WHERE id=2').fetchone()[0], 'team')

    def test_rounds_support_asymmetric_group_and_team_matchups_without_scoring(self):
        self.login()
        with self.app.app_context(), get_db() as db:
            db.executemany('INSERT INTO participants(name, team_id) VALUES (?, ?)', [('Carla', 1), ('David', 2)])
        for values in [dict(format='Equipo vs Equipo', left_team_id=1, right_team_id=2, left_people=[], right_people=[]),
                       dict(format='1vs1'),
                       dict(format='2vs2', left_people=['1', '3'], right_people=['2', '4']),
                       dict(format='1vs2', left_people=['1'], right_people=['2', '4']),
                       dict(format='Relevo especial', left_team_id=1, right_team_id=2, left_people=['1', '3'], right_people=['2'])]:
            self.assertEqual(self.post('rounds', **self.round_data(**values)).status_code, 302)
        with self.app.app_context():
            db = get_db()
            self.assertEqual(db.execute('SELECT COUNT(*) FROM rounds').fetchone()[0], 5)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM round_people').fetchone()[0], 12)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM results').fetchone()[0], 0)
            self.assertTrue(all(row['points'] == 0 for row in leaderboard(db, 'team')))
        public = self.client.get('/challenges').text
        for detail in ('Resultados por rondas', 'Equipo vs Equipo', '1vs1', '2vs2', '1vs2', 'Relevo especial', 'Ana', 'Luis', 'Carla', 'David', 'Verde', 'Azul', 'Ana gana 3–1'):
            self.assertIn(detail, public)
        self.assertEqual(self.client.get('/admin').status_code, 200)

    def test_round_duplicate_submission_is_rejected(self):
        self.login()
        values = self.round_data()
        self.assertEqual(self.post('rounds', **values).status_code, 302)
        self.assertEqual(self.post('rounds', **values).status_code, 409)
        # A replay of a former signed session still cannot duplicate a saved round.
        with self.client.session_transaction() as session:
            session['round_submission'] = values['submission_key']
        self.assertEqual(self.post('rounds', **values).status_code, 409)
        with self.app.app_context():
            self.assertEqual(get_db().execute('SELECT COUNT(*) FROM rounds').fetchone()[0], 1)

    def test_round_invalid_selections_are_atomic(self):
        self.login()
        for overrides in [dict(left_people=[]), dict(right_people=['1']), dict(left_people=['1', '1']),
                          dict(left_people=['999']), dict(left_people=['not-a-number']),
                          dict(left_team_id=999), dict(left_team_id='archived'),
                          dict(left_team_id=1, right_team_id=1), dict(left_people=['archived:1']),
                          dict(round_number=0), dict(round_number=1000), dict(format=''),
                          dict(outcome=''), dict(outcome='x' * 1001), dict(challenge_id=999)]:
            self.assertEqual(self.post('rounds', **self.round_data(**overrides)).status_code, 302)
        with self.app.app_context():
            self.assertEqual(get_db().execute('SELECT COUNT(*) FROM rounds').fetchone()[0], 0)
            self.assertEqual(get_db().execute('SELECT COUNT(*) FROM round_people').fetchone()[0], 0)

    def test_round_writes_require_csrf(self):
        self.login()
        self.assertEqual(self.client.post('/admin/rounds', data=self.round_data()).status_code, 400)
        self.assertEqual(self.client.post('/admin/edit-rounds', data={'round_id': 1}).status_code, 400)

    def test_round_correction_updates_roster_and_rejects_stale_changes(self):
        self.login()
        self.post('rounds', **self.round_data())
        updated = self.round_data(round_id=1, revision=1, round_number=2, format='1vs1 corregido',
                                  left_people=['2'], right_people=['1'], outcome='Luis gana 2–0')
        self.assertEqual(self.post('edit-rounds', **updated).status_code, 302)
        self.assertEqual(self.post('edit-rounds', **updated).status_code, 409)
        with self.app.app_context():
            match = get_db().execute('SELECT * FROM rounds WHERE id=1').fetchone()
            self.assertEqual((match['revision'], match['round_number'], match['outcome']), (2, 2, 'Luis gana 2–0'))
            people = get_db().execute('SELECT side, participant_id FROM round_people ORDER BY side').fetchall()
            self.assertEqual([tuple(row) for row in people], [('left', 2), ('right', 1)])
        self.assertIn('Luis gana 2–0', self.client.get('/challenges').text)
        self.assertEqual(self.post('edit-rounds', **{**updated, 'round_id': 999}).status_code, 404)

    def test_round_snapshot_names_survive_roster_changes_and_deletions(self):
        self.login()
        self.post('rounds', **self.round_data(left_team_id=1, right_team_id=2))
        self.post('edit-participants', participant_id=1, name='Ana nueva')
        self.post('edit-teams', team_id=1, name='Nuevo verde')
        self.post('assign-team', participant_id=1, team_id=2)
        public = self.client.get('/challenges').text
        self.assertIn('<li>Ana</li>', public)
        self.assertIn('<h4>Verde</h4>', public)
        self.delete_confirmed('participants', 1)
        self.delete_confirmed('teams', 1)
        with self.app.app_context():
            db = get_db()
            match = db.execute('SELECT * FROM rounds').fetchone()
            archived_id = db.execute('SELECT id FROM round_people WHERE participant_id IS NULL').fetchone()[0]
            self.assertIsNone(match['left_team_id'])
            self.assertEqual(match['left_team_name'], 'Verde')
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
        self.assertIn('<li>Ana</li>', self.client.get('/challenges').text)
        admin = self.client.get('/admin').text
        self.assertIn('Ana (persona eliminada)', admin)
        self.assertIn('Verde (equipo eliminado)', admin)
        self.post('edit-rounds', **self.round_data(round_id=1, revision=1, left_team_id='archived', right_team_id=2,
                                                  left_people=[f'archived:{archived_id}'], outcome='Resultado corregido'))
        public = self.client.get('/challenges').text
        self.assertIn('Resultado corregido', public)
        self.assertIn('<li>Ana</li>', public)

    def test_challenge_deletion_includes_rounds_and_detects_new_rounds(self):
        self.login()
        ticket = self.deletion_review('challenges', 1)
        self.post('rounds', **self.round_data())
        self.assertEqual(self.post('delete/challenges/1', stage='final', ticket=ticket, confirmation='ELIMINAR').status_code, 409)
        self.assertIn('1 enfrentamientos', self.client.get('/admin/delete/challenges/1').text)
        self.delete_confirmed('challenges', 1)
        with self.app.app_context():
            self.assertEqual(get_db().execute('SELECT COUNT(*) FROM rounds').fetchone()[0], 0)
            self.assertEqual(get_db().execute('SELECT COUNT(*) FROM round_people').fetchone()[0], 0)

    def test_rounds_persist_across_restarts_and_escape_untrusted_text(self):
        self.login()
        self.post('rounds', **self.round_data(format='<script>formato</script>', outcome='<img src=x onerror=alert(1)>'))
        restarted = create_app(self.config)
        with restarted.app_context():
            migrate()
            self.assertEqual(get_db().execute('SELECT COUNT(*) FROM rounds').fetchone()[0], 1)
        public = restarted.test_client().get('/challenges').text
        self.assertIn('&lt;script&gt;formato&lt;/script&gt;', public)
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;', public)
        self.assertNotIn('<script>', public)
        self.assertNotIn('<img', public)

    def test_new_migration_preserves_result_ids_including_deleted_high_water_mark(self):
        database = str(Path(self.directory.name) / 'version-two.sqlite3')
        migrations = Path(__file__).resolve().parents[1] / 'mortezkana/migrations'
        with closing(sqlite3.connect(database)) as db, db:
            db.execute('PRAGMA foreign_keys = ON')
            for name in ('001_initial.sql', '002_roster_management.sql'):
                db.executescript((migrations / name).read_text())
            db.execute('CREATE TABLE schema_migrations (version TEXT PRIMARY KEY)')
            db.executemany('INSERT INTO schema_migrations VALUES (?)', [('001_initial.sql',), ('002_roster_management.sql',)])
            db.execute("INSERT INTO teams(id, name) VALUES (1, 'Equipo original')")
            db.execute("INSERT INTO participants(id, name, team_id) VALUES (1, 'Persona original', 1)")
            db.execute("INSERT INTO challenges(id, name, kind, day) VALUES (1, 'Original', 'hybrid', 1)")
            db.execute("INSERT INTO results(id, challenge_id, team_id, points, notes, revision) VALUES (30, 1, 1, 5, 'Guardado', 4)")
            db.execute("INSERT INTO results(id, challenge_id, participant_id, points) VALUES (99, 1, 1, 7)")
            db.execute('DELETE FROM results WHERE id=99')
        upgraded = create_app({**self.config, 'DATABASE': database})
        with upgraded.app_context():
            migrate()
            db = get_db()
            result = db.execute('SELECT * FROM results WHERE id=30').fetchone()
            self.assertEqual((result['notes'], result['revision'], result['award_kind']), ('Guardado', 4, 'standard'))
            with db:
                cursor = db.execute("INSERT INTO results(challenge_id, participant_id, points) VALUES (1, 1, 7)")
            self.assertGreater(cursor.lastrowid, 99)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def chronology_data(self, identities=None, positions=None):
        page = self.client.get('/admin').text
        # Select the dedicated chronology fingerprint, not deletion form tokens.
        fingerprint = re.search(r'name="fingerprint" value="([a-f0-9]+)"', page).group(1)
        return {'challenge_id': identities if identities is not None else ['1', '2', '3'],
                'position': positions if positions is not None else ['2', '3', '1'],
                'fingerprint': fingerprint}

    def test_chronology_reordering_controls_history_and_public_list_not_days(self):
        self.login()
        self.seed_awards()
        self.assertEqual(self.post('reorder-challenges', **self.chronology_data()).status_code, 302)
        # Change day metadata without changing chronological positions.
        self.post('edit-challenges', challenge_id=3, name='Mixta', kind='hybrid', day=3)
        self.post('edit-challenges', challenge_id=1, name='Individual', kind='individual', day=1)
        with self.app.app_context():
            history = score_history(get_db())
            self.assertEqual([row['id'] for row in history['challenges']], [3, 1, 2])
            self.assertEqual(history['people'][0]['values'], [0, -2, 8, 8])
            self.assertEqual(history['teams'][0]['values'], [0, 2, 12, 18])
            self.assertEqual([row['chronology_position'] for row in history['challenges']], [1, 2, 3])
        public = self.client.get('/challenges').text
        self.assertLess(public.index('<h2>Mixta</h2>'), public.index('<h2>Individual</h2>'))
        self.assertLess(public.index('<h2>Individual</h2>'), public.index('<h2>Equipos</h2>'))

    def test_invalid_chronological_orders_do_not_partially_update(self):
        self.login()
        for identities, positions in [(['1', '2', '3'], ['1', '1', '2']),
                                       (['1', '2', '3'], ['0', '2', '3']),
                                       (['1', '2', '3'], ['1', '2', '4']),
                                       (['1', '2', '3'], ['one', '2', '3']),
                                       (['1', '2'], ['1', '2']),
                                       (['1', '1', '3'], ['1', '2', '3']),
                                       (['1', '2', '999'], ['1', '2', '3']),
                                       (['1', '2', '3'], ['1', '2'])]:
            self.post('reorder-challenges', **self.chronology_data(identities, positions))
            with self.app.app_context():
                rows = get_db().execute('SELECT id, chronology_position FROM challenges ORDER BY id').fetchall()
                self.assertEqual([tuple(row) for row in rows], [(1, 1), (2, 2), (3, 3)])

    def test_chronology_stale_form_is_rejected_after_changes(self):
        self.login()
        values = self.chronology_data()
        self.post('reorder-challenges', **values)
        self.assertEqual(self.post('reorder-challenges', **values).status_code, 409)
        fresh = self.chronology_data()
        self.post('challenges', name='Nueva', kind='individual', day=1)
        self.assertEqual(self.post('reorder-challenges', **fresh).status_code, 409)

    def test_new_challenges_append_and_deletion_compacts_chronology(self):
        self.login()
        self.post('challenges', name='Última', kind='individual', day=1)
        with self.app.app_context():
            self.assertEqual(get_db().execute('SELECT chronology_position FROM challenges WHERE id=4').fetchone()[0], 4)
        self.delete_confirmed('challenges', 2)
        with self.app.app_context():
            rows = get_db().execute('SELECT id, chronology_position FROM challenges ORDER BY chronology_position').fetchall()
            self.assertEqual([tuple(row) for row in rows], [(1, 1), (3, 2), (4, 3)])

    def test_history_only_contains_scored_or_completed_challenges(self):
        self.login()
        with self.app.app_context():
            self.assertEqual(score_history(get_db())['challenges'], [])
        self.assertIn('La evolución aparecerá', self.client.get('/').text)
        self.post('status', challenge_id=2, status='completed')
        self.post('results', challenge_id=3, target='participant:1', points=4, notes='En juego')
        with self.app.app_context():
            history = score_history(get_db())
            self.assertEqual([row['id'] for row in history['challenges']], [2, 3])
            self.assertEqual(history['people'][0]['values'], [0, 0, 4])

    def test_history_matches_rankings_after_extra_awards_corrections_transfers_and_deletion(self):
        self.login()
        self.seed_awards()
        self.post('results', challenge_id=2, target='participant:1', points=7, notes='Ganador')
        self.post('results', challenge_id=2, target='participant:1', points=2, notes='MVP', award_kind='extraordinary')
        self.post('corrections', result_id=1, revision=1, points=12, notes='Corregido')
        self.post('assign-team', participant_id=1, team_id=2)
        self.post('reorder-challenges', **self.chronology_data())
        for target, key in (('participant', 'people'), ('team', 'teams')):
            with self.app.app_context():
                db = get_db()
                self.assertEqual({row['id']: row['values'][-1] for row in score_history(db)[key]},
                                 {row['id']: row['points'] for row in leaderboard(db, target)})
        self.delete_confirmed('challenges', 2)
        with self.app.app_context():
            history = score_history(get_db())
            self.assertEqual(history['people'][0]['values'][-1], 10)
            self.assertEqual({row['id']: row['values'][-1] for row in history['teams']}, {1: 4, 2: 10})

    def test_chart_data_and_finale_names_are_escaped(self):
        self.login()
        self.post('edit-participants', participant_id=1, name='</div><script>alert(1)</script>')
        self.post('edit-challenges', challenge_id=1, name='</div><script>reto</script>', kind='individual', day=1)
        self.post('results', challenge_id=1, target='participant:1', points=10, notes='Validado')
        public = self.client.get('/').text
        self.assertIn('data-history=', public)
        self.assertIn('history.js', public)
        self.assertNotIn('<script>alert(1)</script>', public)
        self.assertIn('Consultar datos de evolución', public)
        self.post('finale', state='unlock')
        final = self.client.get('/final').text
        self.assertNotIn('<script>alert(1)</script>', final)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', final)

    def test_finale_is_locked_server_side_and_can_be_relocked(self):
        self.login()
        self.seed_awards()
        self.assertEqual(self.client.get('/final').status_code, 404)
        self.assertNotIn('La final</a>', self.client.get('/').text)
        self.post('finale', state='unlock')
        public = self.app.test_client()
        self.assertEqual(public.get('/final').status_code, 200)
        self.assertIn('La final</a>', public.get('/').text)
        self.post('finale', state='lock')
        self.assertEqual(public.get('/final').status_code, 404)
        self.assertNotIn('La final</a>', public.get('/').text)

    def test_finale_shows_podium_team_winner_and_global_standings(self):
        self.login()
        self.seed_awards()
        self.post('participants', name='Carla')
        self.post('results', challenge_id=1, target='participant:2', points=6, notes='Segunda')
        self.post('results', challenge_id=1, target='participant:3', points=4, notes='Tercera')
        self.post('finale', state='unlock')
        final = self.client.get('/final').text
        for expected in ('Podio individual', 'podium-place-1', 'podium-place-2', 'podium-place-3',
                         'Equipo ganador', 'Clasificación global', 'Ana', 'Luis', 'Carla', 'Verde', '18'):
            self.assertIn(expected, final)
        self.post('corrections', result_id=1, revision=1, points=3, notes='Corregido')
        updated = self.client.get('/final').text
        self.assertRegex(updated, r'(?s)podium-place-1.*?<h3>Luis</h3>')

    def test_finale_respects_individual_and_team_ties(self):
        self.login()
        self.post('results', challenge_id=1, target='participant:1', points=8, notes='Empate')
        self.post('results', challenge_id=1, target='participant:2', points=8, notes='Empate')
        self.post('finale', state='unlock')
        final = self.client.get('/final').text
        self.assertIn('Empate entre equipos', final)
        self.assertIn('Posición compartida', final)
        self.assertNotIn('podium-place-2', final)
        self.assertRegex(final, r'(?s)podium-place-1.*?<h3>Ana</h3>.*?<h3>Luis</h3>')
        with self.app.app_context(), get_db() as db:
            db.execute('DELETE FROM participants')
            db.execute('DELETE FROM teams')
        self.assertEqual(self.client.get('/final').status_code, 200)
        self.assertIn('Todavía no hay equipos', self.client.get('/final').text)

    def test_finale_and_chronology_writes_require_csrf_and_valid_state(self):
        self.login()
        self.assertEqual(self.client.post('/admin/finale', data={'state': 'unlock'}).status_code, 400)
        self.assertEqual(self.client.post('/admin/reorder-challenges', data=self.chronology_data()).status_code, 400)
        self.post('finale', state='invalid')
        self.assertEqual(self.client.get('/final').status_code, 404)

    def test_chronology_and_finale_state_persist_across_restarts(self):
        self.login()
        self.post('reorder-challenges', **self.chronology_data())
        self.post('finale', state='unlock')
        restarted = create_app(self.config)
        with restarted.app_context():
            migrate()
            rows = get_db().execute('SELECT id FROM challenges ORDER BY chronology_position').fetchall()
            self.assertEqual([row['id'] for row in rows], [3, 1, 2])
        self.assertEqual(restarted.test_client().get('/final').status_code, 200)

    def photo(self, image_format='PNG', size=(400, 200), color=(150, 40, 20), **save_options):
        output = BytesIO()
        Image.new('RGB', size, color).save(output, format=image_format, **save_options)
        return output.getvalue()

    def avatar_post(self, kind='participants', entity_id=1, mode='upload', photo=None, filename='photo.png'):
        with self.client.session_transaction() as session:
            token = session['csrf']
        data = {'csrf': token, 'action': mode}
        if photo is not None:
            data['photo'] = (BytesIO(photo), filename)
        return self.client.post(f'/admin/avatars/{kind}/{entity_id}', data=data)

    def test_default_avatars_are_public_in_standings_and_rosters(self):
        for path in ('/', '/participants'):
            public = self.client.get(path).text
            self.assertIn('/static/avatar-person.svg', public)
            self.assertIn('/static/avatar-team.svg', public)
            self.assertNotIn('type="file"', public)
        with self.client.get('/static/avatar-person.svg') as response:
            self.assertEqual(response.mimetype, 'image/svg+xml')
        with self.client.get('/static/avatar-team.svg') as response:
            self.assertEqual(response.mimetype, 'image/svg+xml')
        response = self.client.get('/avatars/participants/1')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, '/static/avatar-person.svg')

    def test_avatar_uploads_and_reset_require_admin_and_csrf(self):
        self.client.get('/admin/login')
        self.assertEqual(self.avatar_post(photo=self.photo()).status_code, 403)
        self.assertEqual(self.avatar_post(kind='teams', mode='default').status_code, 403)
        self.login()
        self.assertEqual(self.client.post('/admin/avatars/participants/1', data={'action': 'upload', 'photo': (BytesIO(self.photo()), 'photo.png')}).status_code, 400)
        self.assertEqual(self.client.post('/admin/avatars/teams/1', data={'action': 'default'}).status_code, 400)
        with self.app.app_context():
            self.assertIsNone(get_db().execute('SELECT avatar FROM participants WHERE id=1').fetchone()[0])

    def test_uploaded_avatars_are_normalized_persistent_and_visible(self):
        self.login()
        self.seed_awards()
        original = self.photo()
        self.assertEqual(self.avatar_post(photo=original).status_code, 302)
        self.assertEqual(self.avatar_post(kind='teams', photo=self.photo('WEBP')).status_code, 302)
        public = self.app.test_client()
        response = public.get('/avatars/participants/1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'image/jpeg')
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        with Image.open(BytesIO(response.data)) as image:
            self.assertEqual(image.size, (256, 256))
            self.assertEqual(image.format, 'JPEG')
        for path in ('/', '/participants'):
            page = public.get(path).text
            self.assertIn('/avatars/participants/1', page)
            self.assertIn('/avatars/teams/1', page)
        with self.app.app_context():
            history = score_history(get_db())
            self.assertNotIn('has_avatar', history['people'][0])
            self.assertNotIn('avatar', history['teams'][0])
            self.assertEqual(leaderboard(get_db(), 'participant')[0]['points'], 8)
        restarted = create_app(self.config)
        with restarted.app_context():
            migrate()
        self.assertEqual(restarted.test_client().get('/avatars/participants/1').data, response.data)
        self.avatar_post(mode='default')
        self.assertEqual(public.get('/avatars/participants/1').status_code, 302)
        self.assertNotIn('/avatars/participants/1', public.get('/').text)
        self.assertIn('/avatars/teams/1', public.get('/').text)

    def test_invalid_photos_preserve_previous_avatar(self):
        self.login()
        self.avatar_post(photo=self.photo())
        saved = self.client.get('/avatars/participants/1').data
        for photo, filename in [(b'not an image', 'fake.jpg'),
                                (b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', 'image.svg'),
                                (self.photo('GIF'), 'animated.gif'),
                                (self.photo()[:20], 'truncated.png'),
                                (b'x' * (5 * 1024 * 1024 + 1), 'huge.jpg')]:
            self.assertEqual(self.avatar_post(photo=photo, filename=filename).status_code, 302)
            self.assertEqual(self.client.get('/avatars/participants/1').data, saved)
        self.assertEqual(self.avatar_post().status_code, 302)
        self.assertEqual(self.avatar_post(mode='unknown').status_code, 302)
        self.assertEqual(self.client.get('/avatars/participants/1').data, saved)
        self.assertEqual(self.avatar_post(photo=b'x' * (7 * 1024 * 1024)).status_code, 413)

    def test_oversized_pixel_images_are_rejected_before_decoding(self):
        from unittest.mock import patch
        self.login()
        with patch('mortezkana.avatars.Image.MAX_IMAGE_PIXELS', 100):
            self.assertEqual(self.avatar_post(photo=self.photo(size=(20, 20))).status_code, 302)
        with self.app.app_context():
            self.assertIsNone(get_db().execute('SELECT avatar FROM participants WHERE id=1').fetchone()[0])

    def test_avatar_orientation_and_metadata_are_normalized(self):
        self.login()
        source = Image.new('RGB', (400, 200), 'red')
        source.paste('blue', (200, 0, 400, 200))
        exif = Image.Exif()
        exif[274] = 6
        exif[270] = 'Private original metadata'
        data = BytesIO()
        source.save(data, format='JPEG', exif=exif)
        self.avatar_post(photo=data.getvalue(), filename='rotated.jpg')
        with Image.open(BytesIO(self.client.get('/avatars/participants/1').data)) as normalized:
            self.assertEqual(normalized.size, (256, 256))
            self.assertEqual(len(normalized.getexif()), 0)
            top, bottom = normalized.getpixel((128, 30)), normalized.getpixel((128, 220))
            self.assertGreater(top[0], top[2])
            self.assertGreater(bottom[2], bottom[0])

    def test_avatar_target_validation(self):
        self.login()
        for kind, identity in [('unknown', 1), ('participants', 999), ('teams', 999)]:
            self.assertEqual(self.avatar_post(kind=kind, entity_id=identity, photo=self.photo()).status_code, 404)
            self.assertEqual(self.client.get(f'/avatars/{kind}/{identity}').status_code, 404)

    def test_custom_avatars_do_not_break_deletion_confirmations(self):
        self.login()
        self.avatar_post(photo=self.photo())
        self.avatar_post(kind='teams', photo=self.photo(color=(20, 40, 150)))
        ticket = self.deletion_review('teams', 1)
        self.avatar_post(photo=self.photo(color=(40, 150, 20)))
        self.assertEqual(self.post('delete/teams/1', stage='final', ticket=ticket, confirmation='ELIMINAR').status_code, 409)
        self.delete_confirmed('teams', 1)
        self.assertEqual(self.client.get('/avatars/teams/1').status_code, 404)
        self.assertEqual(self.client.get('/avatars/participants/1').status_code, 200)
        self.delete_confirmed('participants', 1)
        self.assertEqual(self.client.get('/avatars/participants/1').status_code, 404)

    def test_finale_admin_control_clearly_hides_public_page(self):
        self.login()
        self.post('finale', state='unlock')
        self.assertIn('Ocultar la pantalla final', self.client.get('/admin').text)
        self.post('finale', state='lock')
        self.assertIn('Pantalla final oculta.', self.client.get('/admin').text)
        public = self.app.test_client()
        self.assertEqual(public.get('/final').status_code, 404)
        self.assertNotIn('La final</a>', public.get('/').text)


if __name__ == '__main__':
    unittest.main()
