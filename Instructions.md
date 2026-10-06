# Deploying Mortezkana on PythonAnywhere

This guide deploys the existing Flask application using PythonAnywhere's standard **Web** tab and WSGI hosting. Commands run in a PythonAnywhere **Bash console** unless stated otherwise. Replace `YOUR_USERNAME` and `YOUR_REPOSITORY_URL` with your own values.

## 1. Choose the hosting environment

Use Python **3.11 or newer**. The examples use Python 3.13; select the same version for the virtual environment and the web app. Available versions depend on your account's system image; check [PythonAnywhere's Python versions](https://help.pythonanywhere.com/pages/PythonVersions/) if 3.13 is unavailable.

The current application supports **SQLite only**. PythonAnywhere supports SQLite but [does not recommend it for production because of its filesystem performance](https://help.pythonanywhere.com/pages/KindsOfDatabases). The following deployment retains SQLite for this small, private weekend competition. Test it with your expected usage and make backups. Moving to MySQL or PostgreSQL requires application changes; changing `DATABASE_PATH` to a connection URL will not work.

Check your plan's availability and expiry before the event. [New free accounts have a one-month web-app expiry](https://blog.pythonanywhere.com/129/); do not assume the site will remain available indefinitely.

## 2. Upload the project and install dependencies

```bash
cd ~
git clone YOUR_REPOSITORY_URL mortezkana
cd ~/mortezkana
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

For a private repository, use your provider's supported authentication method without putting tokens in committed files. Alternatively, upload and extract the source through PythonAnywhere's **Files** tab into `/home/YOUR_USERNAME/mortezkana`. Include the `mortezkana/migrations`, `mortezkana/templates`, and `mortezkana/static` directories. Do not upload your local `.venv`; create it on the server.

## 3. Create persistent configuration

The app does **not** automatically read `.env`. Console environment variables also need to be supplied to the WSGI process. This guide uses a private JSON configuration file, loaded explicitly in both environments, without adding dependencies.

Run this once. It prompts for the administrator password without echoing it, stores its Werkzeug hash, and generates a stable session secret. It refuses to overwrite an existing configuration.

```bash
cd ~/mortezkana
.venv/bin/python - <<'PY'
import getpass
import json
import os
import secrets
from pathlib import Path
from werkzeug.security import generate_password_hash

os.umask(0o077)
config_dir = Path.home() / '.config' / 'mortezkana'
config_dir.mkdir(parents=True, exist_ok=True)
config_dir.chmod(0o700)
config_path = config_dir / 'production.json'
if config_path.exists():
    raise SystemExit('Configuration already exists; preserve it when redeploying.')
password = getpass.getpass('Administrator password: ')
confirmation = getpass.getpass('Confirm password: ')
if not password or password != confirmation:
    raise SystemExit('Passwords must be nonempty and match.')
data_dir = Path.home() / 'mortezkana-data'
data_dir.mkdir(exist_ok=True)
data_dir.chmod(0o700)
config = {
    'SECRET_KEY': secrets.token_hex(32),
    'ADMIN_PASSWORD_HASH': generate_password_hash(password),
    'DATABASE_PATH': str(data_dir / 'competition.sqlite3'),
    'COOKIE_SECURE': '1',
    'MAINTENANCE_MODE': '0',
}
with config_path.open('x') as output:
    json.dump(config, output, indent=2)
config_path.chmod(0o600)
print('Production configuration created.')
PY
```

`SECRET_KEY` signs admin sessions; keep it unchanged across reloads. `ADMIN_PASSWORD_HASH` is a password hash, not the plaintext password. `COOKIE_SECURE=1` requires HTTPS for admin sessions. `MAINTENANCE_MODE` is used by the WSGI wrapper below, rather than by the Flask application itself.

Keep this configuration outside Git. The database path is absolute and outside the checkout so updates preserve competition data. Participants, teams, results, round details, final-screen state, and custom avatar images are all stored in that database.

## 4. Initialize the database

Run this from the project directory on first deployment **and after updates that introduce migrations**:

```bash
cd ~/mortezkana
.venv/bin/python - <<'PY'
import json
import os
from pathlib import Path
from mortezkana import create_app
from mortezkana.db import migrate

config_path = Path.home() / '.config' / 'mortezkana' / 'production.json'
os.environ.update(json.loads(config_path.read_text()))
os.umask(0o077)
app = create_app()
with app.app_context():
    migrate()
print('Database migrations applied.')
PY
```

This runs the same migration function as `flask --app mortezkana init-db`. It applies pending migrations without deleting existing data. Startup does not automatically apply migrations. If transferring an existing competition, use a consistent SQLite backup as described below and apply pending migrations to the restored database.

## 5. Configure the web app

In **Web → Add a new web app**, choose **Manual configuration**, then **Python 3.13** (or the version used in step 2). Set:

| Setting | Value |
| --- | --- |
| Source code | `/home/YOUR_USERNAME/mortezkana` |
| Working directory | `/home/YOUR_USERNAME/mortezkana` |
| Virtualenv | `/home/YOUR_USERNAME/mortezkana/.venv` |

Use the WSGI configuration file linked in the Web tab. Replace its example application code with the following, changing the username in both paths:

```python
import json
import os
import sys
from pathlib import Path

project_dir = '/home/YOUR_USERNAME/mortezkana'
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

config_path = Path('/home/YOUR_USERNAME/.config/mortezkana/production.json')
os.environ.update(json.loads(config_path.read_text()))
os.umask(0o077)

if os.environ.get('MAINTENANCE_MODE') == '1':
    def application(environ, start_response):
        body = 'La aplicación está en mantenimiento. Vuelve en unos minutos.'.encode('utf-8')
        start_response('503 Service Unavailable', [
            ('Content-Type', 'text/plain; charset=utf-8'),
            ('Content-Length', str(len(body))),
            ('Retry-After', '300'),
            ('Cache-Control', 'no-store'),
        ])
        return [body]
else:
    from mortezkana import create_app
    flask_application = create_app()

    def application(environ, start_response):
        # Avatars use send_file(BytesIO(...)); use Werkzeug's file wrapper.
        environ.pop('wsgi.file_wrapper', None)
        return flask_application(environ, start_response)
```

The wrapper avoids PythonAnywhere's [documented `send_file` / `BytesIO` incompatibility](https://help.pythonanywhere.com/pages/FlaskSendFileBytesIO/), which can otherwise break custom avatars. Removing the server-specific wrapper lets Werkzeug use its own in-memory-compatible fallback.

PythonAnywhere runs `application` through its server. Do not start `flask run`, `app.run()`, or Gunicorn in a console for this deployment. See the official [Flask deployment guide](https://help.pythonanywhere.com/pages/Flask).

## 6. Configure static files and HTTPS

In the Web tab's **Static files** section, add:

| URL | Directory |
| --- | --- |
| `/static/` | `/home/YOUR_USERNAME/mortezkana/mortezkana/static` |

The repeated `mortezkana` is intentional: the first directory is the checkout, the second is the Python package. Do not expose the project root, configuration, database, or backups through static mappings. Custom avatars are served through Flask and do not need another mapping. See [static file mappings](https://help.pythonanywhere.com/pages/StaticFiles/).

Enable **Force HTTPS**, then click **Reload**. If using a custom domain, configure a valid HTTPS certificate before forcing HTTPS, as explained in [PythonAnywhere's HTTPS instructions](https://help.pythonanywhere.com/pages/ForcingHTTPS).

Use the domain shown in your Web tab, such as `https://YOUR_USERNAME.pythonanywhere.com` or the EU account equivalent. [Custom domains require a paid account](https://help.pythonanywhere.com/pages/UsingANewDomainForExistingWebApp).

## 7. Verify before the competition

- Open `/`, `/participants`, and `/challenges` on a phone; check styles and the chronology chart.
- Open `/admin/login`, sign in using the password from step 3, and verify an admin session survives navigation over HTTPS.
- Create the people first, then teams, then assign people to teams. Configure challenges and their chronological order.
- Upload a test custom avatar and check it in Participants and Classification.
- Enter a test result, verify individual and team scores, reload the web app, and confirm the data persists. Remove test data through the admin controls before the event.
- Check that `/final` is unavailable while hidden, then test unlocking and hiding it from the admin panel.
- Make the backup below and download a copy before starting real score entry.

## 8. Back up competition data

Run this before updates and regularly during the event. SQLite's backup API creates a consistent snapshot, including custom avatars, without copying a potentially changing database file.

```bash
cd ~/mortezkana
.venv/bin/python - <<'PY'
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

os.umask(0o077)
config = json.loads((Path.home() / '.config/mortezkana/production.json').read_text())
source = Path(config['DATABASE_PATH'])
if not source.is_file():
    raise SystemExit('Configured database does not exist; backup aborted.')
backup_dir = source.parent / 'backups'
backup_dir.mkdir(exist_ok=True)
stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
destination = backup_dir / f'competition-{stamp}.sqlite3'
with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as database:
    with closing(sqlite3.connect(destination)) as backup:
        database.backup(backup)
        result = backup.execute('PRAGMA integrity_check').fetchone()[0]
        if result != 'ok':
            raise SystemExit(f'Backup integrity check failed: {result}')
print(f'Backup created: {destination}')
PY
```

Download the resulting file through the **Files** tab and keep a copy outside PythonAnywhere. Keep a secure separate copy of `production.json` as well; it is not included in database backups.

To restore: enable maintenance as described below and reload first, preserve a backup of the current database, then replace the configured `competition.sqlite3` with your chosen verified snapshot. Do not overwrite a database while workers are accessing it. Apply migrations compatible with the deployed code, disable maintenance, reload, and verify the restored scores. Restoring a snapshot discards changes made after that snapshot.

## 9. Deploy updates

1. Pause score entry. In **Files**, edit `~/.config/mortezkana/production.json`, change `MAINTENANCE_MODE` from `"0"` to `"1"`, save, and **Reload** the web app. Verify it returns the maintenance message before proceeding.
2. Make a database backup using step 8.
3. Update the checkout and dependencies:

   ```bash
   cd ~/mortezkana
   git pull --ff-only
   .venv/bin/python -m pip install -r requirements.txt
   ```

   If originally uploaded manually, upload the updated source instead, preserving the production configuration and data directory.
4. Run the migration snippet from step 4. If installation or migration fails, leave maintenance enabled and inspect the error before continuing.
5. Set `MAINTENANCE_MODE` back to `"0"`, save, and **Reload** in the Web tab. Check public pages, admin login, existing results, and avatars before resuming entry.

Changes become live after a [web-app reload](https://help.pythonanywhere.com/pages/ReloadWebApp/), including configuration changes. Keep `SECRET_KEY`, `ADMIN_PASSWORD_HASH`, and `DATABASE_PATH` stable when updating. For rollback, restore matching code and a pre-update database backup in maintenance mode; migrations are forward-only, so reverting Git alone may not revert the schema.

## Troubleshooting

Check the **error log** and **server log** linked in the Web tab first; see [PythonAnywhere's reload troubleshooting](https://help.pythonanywhere.com/pages/ErrorReloadingWebApp).

| Symptom | Check |
| --- | --- |
| `ModuleNotFoundError` | Virtualenv path, matching Python versions, installed requirements, and checkout root in `sys.path`. |
| Missing secret / password hash error | JSON exists at the WSGI path, contains the required string values, and loads before `create_app()`. |
| `no such table` or missing column | Run step 4 against the same absolute database path used by WSGI. |
| Empty competition after an update | Confirm `DATABASE_PATH` still points at the original database; do not create another database to fix a path error. |
| Login does not persist | Use HTTPS with `COOKIE_SECURE=1`; preserve the session secret. |
| Missing CSS or default avatars | Check the `/static/` mapping and reload; the target is the package's static directory. |
| Avatar raises `fileno` or `uwsgi_sendfile` error | Ensure the WSGI `application` wrapper removes `wsgi.file_wrapper`. |
| `database is locked` | Stop overlapping writes or migrations, inspect active consoles, and retry; repeated locking merits reconsidering SQLite on this host. |
| HTTP 503 maintenance message | Set `MAINTENANCE_MODE` to `"0"` only after the deployment succeeds, then reload. |
| `/final` returns 404 | Expected while the administrator has hidden the final screen. |

Keep debug mode disabled on the public site. Do not post secrets or raw production configuration when sharing logs.
