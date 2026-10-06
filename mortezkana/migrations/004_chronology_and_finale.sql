ALTER TABLE challenges ADD COLUMN chronology_position INTEGER NOT NULL DEFAULT 1
CHECK(chronology_position BETWEEN 1 AND 1000000);
-- Existing challenges start in creation order; day is only descriptive metadata.
UPDATE challenges SET chronology_position = (
    SELECT COUNT(*) FROM challenges earlier WHERE earlier.id <= challenges.id
);
CREATE TABLE competition_settings (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    finale_unlocked INTEGER NOT NULL DEFAULT 0 CHECK(finale_unlocked IN (0, 1))
);
INSERT INTO competition_settings(id) VALUES (1);
