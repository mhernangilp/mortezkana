"""SQLite connections and forward-only, transactional schema migrations."""
from pathlib import Path
import sqlite3

import click
from flask import current_app, g
from flask.cli import with_appcontext


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(current_app.config['DATABASE'], timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
    return g.db


def close_db(_error=None):
    connection = g.pop('db', None)
    if connection is not None:
        connection.close()


def migrate():
    db = get_db()
    db.execute('CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY)')
    db.commit()
    for path in sorted(Path(__file__).with_name('migrations').glob('*.sql')):
        if db.execute('SELECT 1 FROM schema_migrations WHERE version = ?', (path.name,)).fetchone():
            continue
        try:
            db.executescript('BEGIN IMMEDIATE;\n' + path.read_text())
            db.execute('INSERT INTO schema_migrations VALUES (?)', (path.name,))
            db.commit()
        except Exception:
            db.rollback()
            raise


@click.command('init-db')
@with_appcontext
def init_db_command():
    """Apply pending migrations without removing competition data."""
    migrate()
    click.echo('Database migrations applied.')
