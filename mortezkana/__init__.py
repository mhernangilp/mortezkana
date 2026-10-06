import os
from datetime import timedelta
from pathlib import Path

from flask import Flask, render_template
from werkzeug.exceptions import HTTPException

from . import db


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY'),
        ADMIN_PASSWORD_HASH=os.environ.get('ADMIN_PASSWORD_HASH'),
        DATABASE=os.environ.get('DATABASE_PATH', str(Path(app.instance_path) / 'competition.sqlite3')),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE') == '1',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        MAX_CONTENT_LENGTH=32 * 1024,
    )
    if test_config:
        app.config.update(test_config)
    if not app.config['SECRET_KEY'] or not app.config['ADMIN_PASSWORD_HASH']:
        raise RuntimeError('Set SECRET_KEY and ADMIN_PASSWORD_HASH before starting the application.')
    if len(app.config['SECRET_KEY']) < 32:
        raise RuntimeError('SECRET_KEY must contain at least 32 characters.')
    Path(app.config['DATABASE']).parent.mkdir(parents=True, exist_ok=True)
    app.teardown_appcontext(db.close_db)
    app.cli.add_command(db.init_db_command)
    from .views import bp
    app.register_blueprint(bp)

    @app.after_request
    def security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        messages = {400: 'La solicitud no es válida. Recarga la página e inténtalo de nuevo.',
                    403: 'No tienes permiso para realizar esta acción.',
                    404: 'No encontramos esta página.', 409: 'Los datos han cambiado. Recarga la página antes de guardar.',
                    413: 'Los datos enviados son demasiado grandes.'}
        return render_template('error.html', message=messages.get(error.code, 'No se pudo completar la solicitud.')), error.code

    @app.errorhandler(500)
    def server_error(error):
        return render_template('error.html', message='No se pudo completar la operación. Inténtalo de nuevo.'), 500

    return app
