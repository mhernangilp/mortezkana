-- Rebuild both related tables with foreign keys enabled, preserving existing data.
CREATE TABLE participants_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 80),
    team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL
);
INSERT INTO participants_new SELECT id, name, team_id FROM participants;
CREATE TABLE results_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    challenge_id INTEGER NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
    participant_id INTEGER REFERENCES participants_new(id) ON DELETE CASCADE,
    team_id INTEGER REFERENCES teams(id) ON DELETE CASCADE,
    points INTEGER NOT NULL CHECK(points BETWEEN -1000000 AND 1000000),
    notes TEXT NOT NULL DEFAULT '' CHECK(length(notes) <= 500),
    revision INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK((participant_id IS NOT NULL) != (team_id IS NOT NULL)),
    UNIQUE(challenge_id, participant_id),
    UNIQUE(challenge_id, team_id)
);
INSERT INTO results_new SELECT * FROM results;
DROP TABLE results;
DROP TABLE participants;
ALTER TABLE participants_new RENAME TO participants;
ALTER TABLE results_new RENAME TO results;
CREATE TRIGGER participant_limit BEFORE INSERT ON participants
WHEN (SELECT count(*) FROM participants) >= 10
OR (NEW.team_id IS NOT NULL AND (SELECT count(*) FROM participants WHERE team_id = NEW.team_id) >= 5)
BEGIN SELECT RAISE(ABORT, 'participant_limit'); END;
CREATE TRIGGER team_capacity BEFORE UPDATE OF team_id ON participants
WHEN NEW.team_id IS NOT OLD.team_id AND NEW.team_id IS NOT NULL
AND (SELECT count(*) FROM participants WHERE team_id = NEW.team_id) >= 5
BEGIN SELECT RAISE(ABORT, 'participant_limit'); END;
CREATE TRIGGER result_kind_insert BEFORE INSERT ON results
WHEN EXISTS (SELECT 1 FROM challenges WHERE id = NEW.challenge_id AND
    ((kind = 'individual' AND NEW.team_id IS NOT NULL) OR
     (kind = 'team' AND NEW.participant_id IS NOT NULL)))
BEGIN SELECT RAISE(ABORT, 'result_kind'); END;
CREATE TRIGGER result_kind_update BEFORE UPDATE OF challenge_id, participant_id, team_id ON results
WHEN EXISTS (SELECT 1 FROM challenges WHERE id = NEW.challenge_id AND
    ((kind = 'individual' AND NEW.team_id IS NOT NULL) OR
     (kind = 'team' AND NEW.participant_id IS NOT NULL)))
BEGIN SELECT RAISE(ABORT, 'result_kind'); END;
-- Changing a challenge's type must never leave incompatible results behind.
CREATE TRIGGER challenge_kind_update BEFORE UPDATE OF kind ON challenges
WHEN (NEW.kind = 'individual' AND EXISTS (SELECT 1 FROM results WHERE challenge_id = NEW.id AND team_id IS NOT NULL))
OR (NEW.kind = 'team' AND EXISTS (SELECT 1 FROM results WHERE challenge_id = NEW.id AND participant_id IS NOT NULL))
BEGIN SELECT RAISE(ABORT, 'challenge_kind'); END;
