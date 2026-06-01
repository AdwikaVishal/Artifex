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

-- Placement predictions table with ML inference results
CREATE TABLE IF NOT EXISTS placement_predictions (
    id                  SERIAL PRIMARY KEY,
    workflow_id         TEXT NOT NULL,
    child_id            TEXT NOT NULL,
    recommended         JSONB NOT NULL,
    score               REAL,
    confidence          REAL,
    risk_score          REAL DEFAULT 0.0,
    feature_importance  JSONB,
    top_matches         JSONB,
    model_version       TEXT,
    created_at          TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pred_wfid ON placement_predictions(workflow_id);

-- Workflow events timeline
CREATE TABLE IF NOT EXISTS workflow_events (
    id          SERIAL PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    stage       TEXT NOT NULL,
    status      TEXT NOT NULL,
    data        JSONB,
    timestamp   TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wf_events_wfid ON workflow_events(workflow_id);

-- Workflow status tracking
CREATE TABLE IF NOT EXISTS workflow_status (
    workflow_id   TEXT PRIMARY KEY,
    status        TEXT NOT NULL,
    current_stage TEXT,
    progress      INT DEFAULT 0,
    metadata      JSONB,
    updated_at    TIMESTAMP DEFAULT NOW()
);

-- ML inference audit logs
CREATE TABLE IF NOT EXISTS ml_inference_logs (
    id            SERIAL PRIMARY KEY,
    workflow_id   TEXT,
    child_id      TEXT,
    payload       JSONB,
    result        JSONB,
    model_version TEXT,
    timestamp     TIMESTAMP DEFAULT NOW()
);

-- Foster families registry
CREATE TABLE IF NOT EXISTS families (
    id                   SERIAL PRIMARY KEY,
    family_id            TEXT UNIQUE,
    name                 TEXT NOT NULL,
    location             TEXT DEFAULT '',
    capacity             INT  DEFAULT 1,
    -- available_capacity is computed dynamically as capacity - COUNT(active placements)
    experience           TEXT DEFAULT 'new',
    specializations      TEXT DEFAULT '',
    languages            TEXT DEFAULT '',
    special_needs_trained   BOOLEAN DEFAULT FALSE,
    accepts_siblings        BOOLEAN DEFAULT FALSE,
    emergency_available     BOOLEAN DEFAULT FALSE,
    max_age              INT  DEFAULT 18,
    can_take_siblings    BOOLEAN DEFAULT FALSE,
    has_animals          BOOLEAN DEFAULT FALSE,
    created_at           TIMESTAMP DEFAULT NOW(),
    updated_at           TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_families_location ON families(location);

-- Children intake records
CREATE TABLE IF NOT EXISTS children (
    child_id         TEXT PRIMARY KEY,
    age              INT,
    gender           TEXT,
    special_needs    BOOLEAN DEFAULT FALSE,
    sibling_group    BOOLEAN DEFAULT FALSE,
    location         TEXT DEFAULT '',
    languages        TEXT DEFAULT '',
    medical_needs    TEXT DEFAULT '',
    behavioral_support TEXT DEFAULT '',
    intake_reason    TEXT DEFAULT '',
    emergency_level  TEXT DEFAULT 'normal',
    notes            TEXT DEFAULT '',
    created_at       TIMESTAMP DEFAULT NOW(),
    updated_at       TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_children_age ON children(age);
CREATE INDEX IF NOT EXISTS idx_children_location ON children(location);

-- Placement history (training data for ML)
CREATE TABLE IF NOT EXISTS placement_history (
    id               SERIAL PRIMARY KEY,
    child_id         TEXT,
    family_id        TEXT,
    placement_start  DATE,
    placement_end    DATE,
    outcome          TEXT,
    disruption       BOOLEAN DEFAULT FALSE,
    disruption_reason TEXT,
    created_at       TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ph_child_id  ON placement_history(child_id);
CREATE INDEX IF NOT EXISTS idx_ph_family_id ON placement_history(family_id);

-- Check-ins (real-time risk monitoring)
CREATE TABLE IF NOT EXISTS check_ins (
    id                SERIAL PRIMARY KEY,
    child_id          TEXT NOT NULL,
    placement_id      TEXT,
    mood_score        INT DEFAULT 3,
    incident_reported BOOLEAN DEFAULT FALSE,
    notes             TEXT DEFAULT '',
    timestamp         TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_checkins_child_id ON check_ins(child_id);
CREATE INDEX IF NOT EXISTS idx_checkins_timestamp ON check_ins(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_checkins_placement_id ON check_ins(placement_id);

-- Audit log
CREATE TABLE IF NOT EXISTS audit_logs (
    id          SERIAL PRIMARY KEY,
    timestamp   TIMESTAMP DEFAULT NOW(),
    user_id     TEXT,
    role        TEXT,
    action      TEXT NOT NULL,
    target_type TEXT,
    target_id   TEXT,
    details     JSONB,
    ip_address  TEXT,
    user_agent  TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_logs(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_target ON audit_logs(target_type, target_id);

-- Placement History – Historical placement records for ML training
CREATE TABLE IF NOT EXISTS placement_history (
    id                  SERIAL PRIMARY KEY,
    child_id            TEXT NOT NULL,
    family_id           TEXT NOT NULL,
    placement_start     DATE NOT NULL,
    placement_end       DATE NOT NULL,
    outcome             TEXT NOT NULL,
    disruption          BOOLEAN DEFAULT FALSE,
    disruption_reason   TEXT,
    duration_days       INT,
    child_age_at_start  INT,
    removal_reason      TEXT,
    created_at          TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ph_child_id ON placement_history(child_id);
CREATE INDEX IF NOT EXISTS idx_ph_family_id ON placement_history(family_id);
CREATE INDEX IF NOT EXISTS idx_ph_outcome ON placement_history(outcome);
CREATE INDEX IF NOT EXISTS idx_ph_disruption ON placement_history(disruption);
CREATE INDEX IF NOT EXISTS idx_ph_dates ON placement_history(placement_start, placement_end);
