-- Store small normalized photographs alongside the canonical competition data.
ALTER TABLE participants ADD COLUMN avatar BLOB
CHECK(avatar IS NULL OR (typeof(avatar) = 'blob' AND length(avatar) BETWEEN 1 AND 524288));
ALTER TABLE teams ADD COLUMN avatar BLOB
CHECK(avatar IS NULL OR (typeof(avatar) = 'blob' AND length(avatar) BETWEEN 1 AND 524288));
