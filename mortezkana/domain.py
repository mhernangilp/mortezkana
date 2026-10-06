"""Rankings derived from awards and current team membership."""


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
    if target == 'participant':
        rows = db.execute('''
            SELECT p.id, p.name, COALESCE(SUM(r.points), 0) AS points
            FROM participants p LEFT JOIN results r ON r.participant_id = p.id
            GROUP BY p.id, p.name
        ''').fetchall()
    else:
        # Aggregate direct awards and member awards before joining teams, so each
        # result contributes exactly once, even with several members and awards.
        rows = db.execute('''
            SELECT t.id, t.name, COALESCE(SUM(a.points), 0) AS points
            FROM teams t LEFT JOIN (
                SELECT team_id, points FROM results WHERE team_id IS NOT NULL
                UNION ALL
                SELECT p.team_id, r.points FROM results r
                JOIN participants p ON p.id = r.participant_id
                WHERE p.team_id IS NOT NULL
            ) a ON a.team_id = t.id
            GROUP BY t.id, t.name
        ''').fetchall()
    return list(rank([dict(row) for row in rows]))


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
