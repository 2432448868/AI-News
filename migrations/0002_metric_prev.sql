-- 0002: growth tracking — keep the previous collection's metric value so the
-- frontend/API can rank by delta (stars/downloads gained since last pass).
-- Single statement on purpose: ADD COLUMN is not idempotent, so this file
-- must stay alone and only run once per database.
ALTER TABLE items ADD COLUMN metric_prev INTEGER;
