-- Foster care placement schema
-- Run once: docker-compose exec postgres psql -U artifex -d placements -f /scripts/init_db.sql

CREATE TABLE IF NOT EXISTS placements (
    workflow_id      TEXT PRIMARY KEY,
    child_id         TEXT NOT NULL,
    family_id        TEXT NOT NULL,
    family_json      JSONB NOT NULL,
    risk_score       REAL DEFAULT 0.0,
    risk_explanation TEXT,
    risk_history     JSONB DEFAULT '[]',
    last_notes       TEXT,
    removal_reason   TEXT,
    child_age        INTEGER,
    special_needs    BOOLEAN DEFAULT FALSE,
    alert_sent       BOOLEAN DEFAULT FALSE,
    created_at       TIMESTAMP DEFAULT NOW(),
    updated_at       TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_child_id    ON placements(child_id);
CREATE INDEX IF NOT EXISTS idx_risk_score  ON placements(risk_score DESC);
CREATE INDEX IF NOT EXISTS idx_updated_at  ON placements(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_family_id   ON placements(family_id);

-- Auto-update updated_at on every row change
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS placements_updated_at ON placements;
CREATE TRIGGER placements_updated_at
    BEFORE UPDATE ON placements
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
