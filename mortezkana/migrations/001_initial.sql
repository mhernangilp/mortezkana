CREATE TABLE teams (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE CHECK(length(name) BETWEEN 1 AND 80)
);
CREATE TRIGGER team_limit BEFORE INSERT ON teams
WHEN (SELECT count(*) FROM teams) >= 2
BEGIN SELECT RAISE(ABORT, 'team_limit'); END;
CREATE TABLE participants (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 80),
    team_id INTEGER NOT NULL REFERENCES teams(id)
);
CREATE TRIGGER participant_limit BEFORE INSERT ON participants
WHEN (SELECT count(*) FROM participants) >= 10
OR (SELECT count(*) FROM participants WHERE team_id = NEW.team_id) >= 5
BEGIN SELECT RAISE(ABORT, 'participant_limit'); END;
CREATE TRIGGER team_capacity BEFORE UPDATE OF team_id ON participants
WHEN NEW.team_id != OLD.team_id
AND (SELECT count(*) FROM participants WHERE team_id = NEW.team_id) >= 5
BEGIN SELECT RAISE(ABORT, 'participant_limit'); END;
CREATE TABLE challenges (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 80),
    description TEXT NOT NULL DEFAULT '' CHECK(length(description) <= 2000),
    kind TEXT NOT NULL CHECK(kind IN ('individual', 'team', 'hybrid')),
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'active', 'completed')),
    day INTEGER NOT NULL CHECK(day BETWEEN 1 AND 3)
);
-- One authoritative award per challenge and target. Corrections replace this award.
-- Hybrid challenges have independent individual and team awards: no implicit aggregation.
CREATE TABLE results (
    id INTEGER PRIMARY KEY,
    challenge_id INTEGER NOT NULL REFERENCES challenges(id),
    participant_id INTEGER REFERENCES participants(id),
    team_id INTEGER REFERENCES teams(id),
    points INTEGER NOT NULL CHECK(points BETWEEN -1000000 AND 1000000),
    notes TEXT NOT NULL DEFAULT '' CHECK(length(notes) <= 500),
    revision INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK((participant_id IS NOT NULL) != (team_id IS NOT NULL)),
    UNIQUE(challenge_id, participant_id),
    UNIQUE(challenge_id, team_id)
);
CREATE TRIGGER result_kind_insert BEFORE INSERT ON results
WHEN EXISTS (SELECT 1 FROM challenges WHERE id = NEW.challenge_id AND
    ((kind = 'individual' AND NEW.team_id IS NOT NULL) OR
     (kind = 'team' AND NEW.participant_id IS NOT NULL)))
BEGIN SELECT RAISE(ABORT, 'result_kind'); END;
