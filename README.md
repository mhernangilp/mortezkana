# Mortezkana

A small, mobile-first competition app for one weekend: two teams, ten participants,
and three days of individual, team, and hybrid challenges. All application copy is Spanish.

## Stack

Python 3.11+, Flask, server-rendered Jinja templates, and SQLite. No JavaScript build
pipeline, external accounts, or separate database service. The application follows
Flask's [application factory pattern](https://flask.palletsprojects.com/en/stable/patterns/appfactories/).

## Local setup

```bash
make install
export SECRET_KEY="$(.venv/bin/python -c 'import secrets; print(secrets.token_hex(32))')"
export ADMIN_PASSWORD_HASH="$(.venv/bin/python -c 'from getpass import getpass; from werkzeug.security import generate_password_hash; print(generate_password_hash(getpass("Admin password: ")))')"
make init
make dev
```

Open http://127.0.0.1:5000. `/admin` redirects to the administrator login.
Keep `SECRET_KEY` and the password hash stable across restarts; configure them using
your hosting provider's secrets or a local shell environment. `.env.example` documents
the available settings; the application does not automatically load `.env` files.
Never commit credentials. The app deliberately refuses to start without its secrets.

## Included foundations

- Public individual/team standings, challenge list, and team rosters.
- Admin login/logout and forms for teams, participants, challenges, challenge status,
  result entry, and result corrections grouped in collapsible sections per challenge.
- Create people first, create teams second, then assign or transfer existing people.
  People can remain unassigned; current members' individual awards contribute to their
  team's standing, alongside direct team awards.
- Edit people, teams, and challenges; delete them through two server-validated
  confirmation screens. Final confirmation requires typing `ELIMINAR` and expires
  after ten minutes. Any relevant data change requires reviewing the deletion again.
- Completed challenges show individual and direct team award summaries in both the
  public challenge list and administrator result groups.
- Database constraints for two teams, ten participants, five per team, valid references,
  challenge types, and unique results.
- Signed, eight-hour admin sessions; server-side authorization; CSRF protection on
  every POST; escaped templates and restrictive browser security headers.
- Transactional forward migrations, persistent results, centralized ranking calculation,
  and optimistic concurrency checks for result corrections.

Setup may contain fewer than ten participants while the administrator enters the roster.
There are no fabricated names, results, or scoring formulas. The administrator enters
whole-number awards according to the rules of each challenge. Negative awards are
supported. Each challenge has one result per participant or team; corrections replace
that result instead of adding it again. A repeated submission cannot duplicate points.
Team totals sum direct team awards and the individual awards of their current members.
Moving a person transfers their individual contribution immediately without changing
their own results or moving awards granted directly to the old team. Unassigned people
retain individual scores but contribute to no team. For a hybrid challenge, only enter
a direct team award when its rules grant additional team points; entering the same
individual contribution again as a team award would count it twice.

Deleting a person removes their individual results. Deleting a challenge removes all
of its individual and team results. Deleting a team removes direct awards to that team
and leaves its people unassigned, retaining their individual results. Cascades and
unassignments are atomic database operations, and all standings derive from the
remaining records. Each confirmation screen explains the affected scores.
Challenge types cannot be changed to a type incompatible with recorded results.

For existing installations, run `make init` with your existing environment configured
before starting the updated application. Migration `002_roster_management.sql`
preserves existing IDs, roster assignments, results, notes, and correction revisions.

Equal scores share the same rank (1, 1, 3). Alphabetical ordering only makes ties
stable on screen; it does not decide winners. Specific scoring formulas, tiebreaks,
match/tournament formats, bonuses/penalties as separate records, final winner selection,
and statistics/charts await their own requirements.

## Checks

```bash
make check
```

Uses Python's standard-library `unittest`; tests create disposable databases and require
no external service. Covers authorization, CSRF, ranking ties, negative scores, hybrid
awards, duplicate submissions, correction conflicts, capacity constraints, validation,
HTML escaping, transactional rollback, persistence, repeatable migrations, transfer
and unassignment scoring, two-stage deletion enforcement, deletion cascades, editing,
completed challenge summaries, and migration from the original populated schema.

## Deployment and persistence

Run migrations once before starting the server, then serve behind HTTPS:

```bash
export COOKIE_SECURE=1
export DATABASE_PATH=/path/to/persistent-volume/competition.sqlite3
make init
.venv/bin/gunicorn --bind 0.0.0.0:8000 --workers 1 'mortezkana:create_app()'
```

Also configure `SECRET_KEY` and `ADMIN_PASSWORD_HASH` as above. Use a single application
instance with a persistent writable disk. Do not place the database in an ephemeral
container filesystem, deploy multiple replicas with separate files, or use SQLite on
a network filesystem. The Flask development server is for local development only.
No deployment is provisioned by this repository.

Back up the live database using SQLite's backup API rather than copying a potentially
active database file:

```bash
.venv/bin/python -c 'import os, sqlite3; source = sqlite3.connect(os.environ["DATABASE_PATH"]); target = sqlite3.connect("competition-backup.sqlite3"); source.backup(target); target.close(); source.close()'
```

Store backups off the application host and keep them out of version control. For restore,
stop the app, restore the backup to `DATABASE_PATH`, and restart with the same secrets.
The public pages expose competition names and scores to anyone with the URL. Only
administrator writes require login. Restrict administrator login attempts at the HTTPS
reverse proxy when publishing to the internet.

## Layout

- `mortezkana/__init__.py`: application configuration and shared error/security handling.
- `mortezkana/db.py` and `migrations/`: connections and authoritative schema.
- `mortezkana/domain.py`: derived rankings, independent from presentation.
- `mortezkana/views.py`: read routes, authentication, validation, admin mutations.
- `mortezkana/templates/` and `static/`: responsive Spanish interface.
- `tests/`: domain and integration tests.
