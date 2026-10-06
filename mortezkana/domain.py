"""Rankings derived from awards and current team membership."""

INDIVIDUAL_POINTS = (10, 8, 6, 5, 4, 3, 2, 2, 1, 1)
HYBRID_TEAM_POINTS = {'win': 3, 'loss': 1}
HYBRID_INDIVIDUAL_POINTS = {'win': 3, 'loss': 1}
TEAM_MEMBER_POINTS = {'win': 7, 'loss': 3}

# Rankings and chronological charts share exactly the same award sources.
AWARD_QUERIES = {
    'participant': 'SELECT challenge_id, participant_id AS target_id, points FROM results WHERE participant_id IS NOT NULL',
    'team': '''SELECT challenge_id, team_id AS target_id, points FROM results WHERE team_id IS NOT NULL
        UNION ALL
        SELECT r.challenge_id, p.team_id AS target_id, r.points FROM results r
        JOIN participants p ON p.id = r.participant_id WHERE p.team_id IS NOT NULL''',
}


def rank(entries):
    ordered = sorted(entries, key=lambda row: (-row['points'], row['name'].casefold(), row['id']))
    previous = None
    position = 0
    for index, row in enumerate(ordered, 1):
        if row['points'] != previous:
            position = index
        yield {**row, 'rank': position}
        previous = row['points']


def leaderboard(db, target):
    if target not in ('participant', 'team'):
        raise ValueError('Unknown leaderboard target')
    table = 'participants' if target == 'participant' else 'teams'
    # All interpolated SQL identifiers/queries come from fixed internal choices.
    rows = db.execute(f'''
        SELECT t.id, t.name, (t.avatar IS NOT NULL) AS has_avatar, COALESCE(SUM(a.points), 0) AS points
        FROM {table} t LEFT JOIN ({AWARD_QUERIES[target]}) a ON a.target_id = t.id
        GROUP BY t.id, t.name
    ''').fetchall()
    return list(rank([dict(row) for row in rows]))


def score_history(db):
    """Cumulative awards by configured challenge order, using current membership."""
    challenges = [dict(row) for row in db.execute('''
        SELECT id, name, status, chronology_position FROM challenges
        WHERE status = 'completed' OR EXISTS (SELECT 1 FROM results WHERE challenge_id = challenges.id)
        ORDER BY chronology_position, id
    ''')]
    history = {'challenges': challenges}
    for target, key in (('participant', 'people'), ('team', 'teams')):
        awards = {}
        for row in db.execute(AWARD_QUERIES[target]):
            identity = (row['challenge_id'], row['target_id'])
            awards[identity] = awards.get(identity, 0) + row['points']
        series = []
        for entrant in leaderboard(db, target):
            values = [0]
            for challenge in challenges:
                values.append(values[-1] + awards.get((challenge['id'], entrant['id']), 0))
            series.append({'id': entrant['id'], 'name': entrant['name'], 'values': values})
        history[key] = series
    return history


def chronology_fingerprint(challenges):
    """Detect another administrator tab changing the order or challenge list."""
    import hashlib
    import json
    data = [(row['id'], row['chronology_position']) for row in challenges]
    return hashlib.sha256(json.dumps(data).encode()).hexdigest()


def reorder_challenges(db, identities, positions, fingerprint):
    rows = db.execute('SELECT id, chronology_position FROM challenges ORDER BY chronology_position, id').fetchall()
    if fingerprint != chronology_fingerprint(rows):
        return False
    if (len(identities) != len(rows) or len(set(identities)) != len(rows)
            or set(identities) != {row['id'] for row in rows}
            or sorted(positions) != list(range(1, len(rows) + 1))):
        raise ValueError('Asigna una posición distinta a cada prueba, desde 1 hasta el número total de pruebas.')
    db.executemany('UPDATE challenges SET chronology_position=? WHERE id=?', zip(positions, identities))
    return True


def compact_chronology(db):
    rows = db.execute('SELECT id FROM challenges ORDER BY chronology_position, id').fetchall()
    db.executemany('UPDATE challenges SET chronology_position=? WHERE id=?',
                   [(position, row['id']) for position, row in enumerate(rows, 1)])


def challenge_results(db):
    """Group awards for both public summaries and administrator corrections."""
    grouped = {}
    rows = db.execute('''
        SELECT r.*, COALESCE(p.name, t.name) AS target_name,
               CASE WHEN r.participant_id IS NOT NULL THEN 'individual' ELSE 'team' END AS target_kind
        FROM results r
        LEFT JOIN participants p ON p.id = r.participant_id
        LEFT JOIN teams t ON t.id = r.team_id
        ORDER BY r.challenge_id, target_kind, r.points DESC, target_name, r.id
    ''').fetchall()
    for row in rows:
        grouped.setdefault(row['challenge_id'], []).append(row)
    return grouped
