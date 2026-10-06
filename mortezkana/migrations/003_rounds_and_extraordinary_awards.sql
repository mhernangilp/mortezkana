-- Keep ordinary and extraordinary awards separate, with duplicate protection for each.
CREATE TEMP TABLE previous_result_sequence AS SELECT seq FROM sqlite_sequence WHERE name = 'results';
CREATE TABLE results_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    challenge_id INTEGER NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
    participant_id INTEGER REFERENCES participants(id) ON DELETE CASCADE,
    team_id INTEGER REFERENCES teams(id) ON DELETE CASCADE,
    points INTEGER NOT NULL CHECK(points BETWEEN -1000000 AND 1000000),
    notes TEXT NOT NULL DEFAULT '' CHECK(length(notes) <= 500),
    revision INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    award_kind TEXT NOT NULL DEFAULT 'standard' CHECK(award_kind IN ('standard', 'extraordinary')),
    CHECK((participant_id IS NOT NULL) != (team_id IS NOT NULL)),
    CHECK(award_kind != 'extraordinary' OR participant_id IS NOT NULL),
    UNIQUE(challenge_id, participant_id, award_kind),
    UNIQUE(challenge_id, team_id)
);
INSERT INTO results_new(id, challenge_id, participant_id, team_id, points, notes, revision, updated_at)
SELECT id, challenge_id, participant_id, team_id, points, notes, revision, updated_at FROM results;
UPDATE sqlite_sequence SET seq = MAX(seq, COALESCE((SELECT seq FROM previous_result_sequence), seq))
WHERE name = 'results_new';
INSERT INTO sqlite_sequence(name, seq)
SELECT 'results_new', seq FROM previous_result_sequence
WHERE NOT EXISTS (SELECT 1 FROM sqlite_sequence WHERE name = 'results_new');
DROP TABLE previous_result_sequence;
DROP TRIGGER challenge_kind_update;
DROP TABLE results;
ALTER TABLE results_new RENAME TO results;
CREATE TRIGGER result_kind_insert BEFORE INSERT ON results
WHEN EXISTS (SELECT 1 FROM challenges WHERE id = NEW.challenge_id AND
    ((kind = 'individual' AND NEW.team_id IS NOT NULL) OR
     (NEW.award_kind = 'extraordinary' AND kind != 'team')))
BEGIN SELECT RAISE(ABORT, 'result_kind'); END;
CREATE TRIGGER result_kind_update BEFORE UPDATE OF challenge_id, participant_id, team_id, award_kind ON results
WHEN EXISTS (SELECT 1 FROM challenges WHERE id = NEW.challenge_id AND
    ((kind = 'individual' AND NEW.team_id IS NOT NULL) OR
     (NEW.award_kind = 'extraordinary' AND kind != 'team')))
BEGIN SELECT RAISE(ABORT, 'result_kind'); END;
CREATE TRIGGER challenge_kind_update BEFORE UPDATE OF kind ON challenges
WHEN (NEW.kind = 'individual' AND EXISTS (SELECT 1 FROM results WHERE challenge_id = NEW.id AND team_id IS NOT NULL))
OR (NEW.kind != 'team' AND EXISTS (SELECT 1 FROM results WHERE challenge_id = NEW.id AND award_kind = 'extraordinary'))
BEGIN SELECT RAISE(ABORT, 'challenge_kind'); END;

-- Round records are informational: they never award leaderboard points.
CREATE TABLE rounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    challenge_id INTEGER NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
    round_number INTEGER NOT NULL CHECK(round_number BETWEEN 1 AND 999),
    format TEXT NOT NULL CHECK(length(format) BETWEEN 1 AND 80),
    left_team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL,
    right_team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL,
    left_team_name TEXT NOT NULL DEFAULT '' CHECK(length(left_team_name) <= 80),
    right_team_name TEXT NOT NULL DEFAULT '' CHECK(length(right_team_name) <= 80),
    outcome TEXT NOT NULL CHECK(length(outcome) BETWEEN 1 AND 1000),
    revision INTEGER NOT NULL DEFAULT 1,
    submission_key TEXT NOT NULL UNIQUE
);
CREATE TABLE round_people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    round_id INTEGER NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
    side TEXT NOT NULL CHECK(side IN ('left', 'right')),
    participant_id INTEGER REFERENCES participants(id) ON DELETE SET NULL,
    participant_name TEXT NOT NULL CHECK(length(participant_name) BETWEEN 1 AND 80),
    UNIQUE(round_id, participant_id)
);
