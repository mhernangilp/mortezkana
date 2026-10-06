# Mortezkana

A small, mobile-first competition app for one weekend: two teams, ten participants,
and three days of individual, team, and hybrid challenges. All application copy is Spanish.

## Stack

Python 3.11+, Flask, server-rendered Jinja templates, SQLite, and Pillow for avatar
photo validation and resizing. No JavaScript build
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
- Default avatars and administrator-uploaded photos for people and teams, visible in
  standings and team rosters. The chronological chart contains no avatars.
- Cumulative score chart in the standings, switchable between people and teams.
  Supports showing/hiding series, selecting a challenge, touch and keyboard navigation,
  negative scores, responsive layout, and a text alternative without JavaScript.
- Administrator-controlled challenge chronology, independent of the informative day
  label. Orders are saved atomically with validation and stale-form protection.
- A server-gated final celebration page with an individual podium, winning teams,
  complete rankings, finite animations, and reduced-motion support. Admin can unlock
  or relock it; the persisted gate applies even to direct requests to `/final`.
- Admin login/logout and forms for teams, participants, challenges, challenge status,
  result entry, and result corrections grouped in collapsible sections per challenge.
- Create people first, create teams second, then assign or transfer existing people.
  People can remain unassigned; current members' individual awards contribute to their
  team's standing, alongside direct team awards.
- Edit people, teams, and challenges; delete them through two server-validated
  confirmation screens. Final confirmation requires typing `ELIMINAR` and expires
  after ten minutes. Any relevant data change requires reviewing the deletion again.
- Completed challenges show individual and direct team award summaries in both the
  public challenge list and administrator result groups, including each result's notes.
- Public and admin scoring reference: individual positions award 10, 8, 6, 5, 4, 3, 2, 2, 1, 1;
  hybrid individual wins/losses receive +3/+1; hybrid team winners/losers receive +3/+1;
  team-only winners/losers receive +7/+3
  per person. This is a manual-entry guide, not automatic scoring.
- Team-only challenges accept ordinary individual awards plus a separate extraordinary
  individual award (such as MVP). Both contribute to the person and their current team.
- Informational rounds with free matchup formats, optional teams and individually
  selected people on each side, written outcomes, and corrections. Rounds appear
  publicly even before a challenge is completed and never award leaderboard points.
- Database constraints for two teams, ten participants, five per team, valid references,
  challenge types, and unique results.
- Signed, eight-hour admin sessions; server-side authorization; CSRF protection on
  every POST; escaped templates and restrictive browser security headers.
- Transactional forward migrations, persistent results, centralized ranking calculation,
  and optimistic concurrency checks for result corrections.

Setup may contain fewer than ten participants while the administrator enters the roster.
There are no fabricated names, results, or scoring formulas. The administrator enters
whole-number awards according to the rules of each challenge. Negative awards are
supported. Each challenge has one ordinary result per participant or team; team-only
challenges may also have one extraordinary result per participant. Corrections replace
the selected result instead of adding it again. A repeated submission cannot duplicate points.
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

Use the `Rondas` section inside each challenge's administrator result group to record
or correct matchups. Multiple matchups can share a round number. Formats such as
`Equipo vs Equipo`, `1vs1`, `2vs2`, and `1vs2` are suggestions; any descriptive format
is accepted. Each side needs a team or at least one person; a person cannot appear
on both sides and a team cannot oppose itself. Team selection does not automatically
select its roster: choose the actual people when you want to show them.
Names are saved at the time of recording, so subsequent roster changes or deletions
do not erase the historical matchup. Deleting a challenge also deletes all its rounds.
Round submissions reject duplicate sends, and corrections reject stale revisions.

## Avatars and public scoring guide

Everyone can open `Chuleta de puntuaciones` on the public `Pruebas` page, including
without administrator login. The same reference remains available in administration.

Open a person or team in administration to upload a photo or restore the default avatar.
Uploads require administrator authorization and CSRF protection. Supported photos are
JPEG, PNG, and WebP, up to 5 MB and 20 megapixels. Files are decoded and validated rather
than trusted by extension, orientation is normalized, metadata is removed, and a square
256×256 JPEG is stored. Transparent photos are flattened on a neutral background.
Unsupported or corrupt uploads preserve the previous avatar. Public users can view
avatars but cannot change them.

Photos are stored directly in SQLite, so they survive restarts and are included in the
normal database backup. Original images are not retained, and no external image host or
separate persistent upload volume is needed. Existing people and teams start with bundled
default SVG avatars. Avatar URLs and image bytes are not included in chronological data.

## Chronology and final celebration

Use `Orden cronológico de las pruebas` in administration to assign each challenge a
distinct position from 1 to the total number of challenges, then save the complete
order. Changing a challenge's day does not change this order. New challenges append
to the end; deletion closes gaps. Existing challenges initially use their creation order.
The public challenge list and administrator selectors follow this same chronology.

The chart starts at zero and includes challenges with saved awards or completed status.
Unplayed challenges without awards are omitted; completed challenges without awards
keep scores flat. Values include ordinary and extraordinary awards and recompute from
the same data as the standings. Historical team curves use current membership, matching
the existing rule that moving a person transfers their contribution. Corrections and
reordering update the curve; informational rounds do not award points.

Use `Pantalla de finalización` to unlock or relock `/final`. Once unlocked, its link
appears in public navigation and standings. The celebration reflects current scores,
including later corrections; it does not freeze data or require every challenge to be
completed. The podium includes everyone in positions 1–3, with shared ranks for ties.
Tied leading teams are displayed together rather than assigning an arbitrary winner.
The `Ocultar la pantalla final` button removes its public links and blocks direct access
again, without changing competition scores.

For existing installations, run `make install` to update dependencies, then `make init`
with your existing environment configured
before starting the updated application. Migrations preserve existing IDs, roster
assignments, results, notes, and correction revisions. Migration
`003_rounds_and_extraordinary_awards.sql` marks existing results as ordinary awards;
`004_chronology_and_finale.sql` initializes chronology and keeps the final page locked.
`005_avatars.sql` adds optional photo storage without changing scores or final visibility.

Equal scores share the same rank (1, 1, 3). Alphabetical ordering only makes ties
stable on screen; it does not decide winners. Automatic scoring, tiebreaks,
tournament progression, additional bonus/penalty workflows, and additional statistics
await their own requirements.

## Checks

```bash
make check
```

Uses Python's standard-library `unittest`; tests create disposable databases and require
no external service. Covers authorization, CSRF, ranking ties, negative scores, hybrid
awards, duplicate submissions, correction conflicts, capacity constraints, validation,
HTML escaping, transactional rollback, persistence, repeatable migrations, transfer
and unassignment scoring, two-stage deletion enforcement, deletion cascades, editing,
completed challenge summaries and notes, ordinary/extraordinary awards, round validation,
round correction conflicts, historical names, and migration from populated prior schemas.
Also covers chronology validation, score history consistency, final gating and persistence,
podium ties, and escaping chart/celebration data.
Avatar checks cover authorization, CSRF, formats, size and pixel limits, orientation,
metadata removal, replacement/reset, persistence, and deletion confirmation snapshots.

An optional browser smoke test checks the interactive chart, real admin login and
chronology forms, avatar upload/display, the public scoring guide, show/hide flow,
reduced-motion styling, and layouts at 320, 390,
and 1280 pixels using a disposable local database. Playwright is only a testing tool;
it is not needed to run the app:

```bash
.venv/bin/python -m pip install playwright
.venv/bin/python -m playwright install chromium
make browser-check
```

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
- `mortezkana/avatars.py`: photo validation and normalized JPEG generation.
- `mortezkana/rounds.py`: round validation, transactional writes, and historical matchups.
- `mortezkana/views.py`: read routes, authentication, validation, admin mutations.
- `mortezkana/templates/` and `static/`: responsive Spanish interface.
- `scripts/check_browser.py`: optional interactive Chromium smoke check.
- `tests/`: domain and integration tests.
