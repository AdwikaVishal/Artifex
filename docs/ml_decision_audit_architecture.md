# ML Decision Audit Architecture

Tamper-evident audit trail for every ML recommendation made by Artifex — placement matches, risk scores, crisis predictions, and resource assignments.

---

## 1. Per-Decision Capture

### 1.1 Decision types audited

| Decision type | Trigger | Model | Logged in |
|---|---|---|---|
| `placement_match` | `publish_match_activity` | `placement_model.pkl` (XGBoost) | `ml_decision_audit` |
| `risk_score` | `compute_risk_activity` | `risk_model.pkl` (XGBoost) | `ml_decision_audit` |
| `crisis_prediction` | `predict_and_store` | `crisis_drift_model.pkl` (XGBoost) | `ml_decision_audit` |
| `family_recommendation` | `rank_families` | `placement_model.pkl` (XGBoost) | `ml_decision_audit` |
| `human_override` | POST `/api/approve` with override | N/A (human) | `ml_decision_audit` + `audit_logs` |

### 1.2 `ml_decision_audit` schema

```sql
CREATE TABLE ml_decision_audit (
    id                SERIAL PRIMARY KEY,

    -- 1. WHO
    child_id          TEXT        NOT NULL REFERENCES children(child_id),
    placement_id      TEXT        REFERENCES placements(workflow_id),
    caseworker_id     TEXT,

    -- 2. WHAT
    decision_type     TEXT        NOT NULL
                        CHECK (decision_type IN (
                          'placement_match', 'risk_score', 'crisis_prediction',
                          'family_recommendation', 'human_override'
                        )),
    model_name        TEXT,                    -- e.g. 'crisis_drift_model_v2.3'
    model_version     TEXT,                    -- e.g. 'v2.3'
    feature_hash      TEXT,                    -- SHA-256 of ordered feature vector (for data-drift tracking)

    -- 3. INPUT
    input_features    JSONB       NOT NULL,    -- full feature vector used by the model
    child_demographics JSONB     NOT NULL,     -- age, gender, race, fpl_percent, zip_code, special_needs

    -- 4. OUTPUT
    output_score      DOUBLE PRECISION,        -- raw model score (e.g. disruption probability 0–100)
    output_label      TEXT,                    -- binned label: 'low' / 'medium' / 'high' / 'critical'
    output_confidence DOUBLE PRECISION,        -- model confidence if available
    output_details    JSONB,                   -- top_k_recommendations, SHAP values, interventions

    -- 5. HUMAN FACTOR
    human_overridden  BOOLEAN     NOT NULL DEFAULT FALSE,
    human_decision    TEXT,                    -- 'approved' / 'rejected' / 'modified'
    human_comment     TEXT,
    overridden_by     TEXT,                    -- user_id of the caseworker/supervisor
    overridden_at     TIMESTAMP,

    -- 6. AUDIT INFRASTRUCTURE
    decided_at        TIMESTAMP   NOT NULL DEFAULT NOW(),
    ingested_at       TIMESTAMP   NOT NULL DEFAULT NOW(),
    prev_hash         TEXT,                    -- SHA-256 of previous row's hash
    hash              TEXT,                    -- SHA-256 of this row

    CONSTRAINT uq_decision UNIQUE (child_id, decision_type, decided_at)
);

CREATE INDEX idx_ml_audit_child          ON ml_decision_audit (child_id);
CREATE INDEX idx_ml_audit_type           ON ml_decision_audit (decision_type);
CREATE INDEX idx_ml_audit_demographics   ON ml_decision_audit USING GIN (child_demographics);
CREATE INDEX idx_ml_audit_features       ON ml_decision_audit USING GIN (input_features);
CREATE INDEX idx_ml_audit_score          ON ml_decision_audit (output_score DESC);
CREATE INDEX idx_ml_audit_decided_at     ON ml_decision_audit (decided_at DESC);
CREATE INDEX idx_ml_audit_model_ver      ON ml_decision_audit (model_version);
CREATE INDEX idx_ml_audit_hash           ON ml_decision_audit (hash);
```

### 1.3 `child_demographics` JSONB structure

```json
{
  "age": 9,
  "age_group": "6-12",
  "gender": "F",
  "race": "Black or African American",
  "fpl_percent": 85,
  "zip_code": "606",
  "special_needs": true,
  "sibling_group": false,
  "emergency_level": "emergency"
}
```

Stored separately from `input_features` so compliance officers can filter by demographic attributes without parsing the full feature vector.

### 1.4 `input_features` JSONB structure (example — crisis prediction)

```json
{
  "age": 9,
  "special_needs": 1,
  "sibling_present": 0,
  "placement_week": 14,
  "disruption_rate_similar": 0.18,
  "school_attendance_rate": 0.70,
  "school_attendance_trend": -0.08,
  "school_attendance_delta": -0.22,
  "school_attendance_volatility": 0.12,
  "incident_count_28d": 8,
  "incident_severity_trend": 0.31,
  "incident_severity_avg": 2.6,
  "caseworker_sentiment_avg": -0.42,
  "caseworker_sentiment_trend": -0.26,
  "medication_compliance_rate": 0.77,
  "communication_response_rate": 0.58,
  "communication_lag_hours": 18.5
}
```

### 1.5 Hash chain computation

Same algorithm as the existing `audit_logs` hash chain:

```
hash_input = f"{prev_hash}|{decision_type}|{child_id}|{decided_at}|{output_score}|{model_version}"
hash = SHA-256(hash_input.encode()).hexdigest()
```

The hash chain is per-table (`ml_decision_audit` is a standalone hash chain, independent of `audit_logs`). This keeps the ML decision audit trail self-contained and verifiable without traversing user-action logs.

### 1.6 Human override capture

When a caseworker rejects or modifies an ML recommendation (e.g. POST `/api/approve` with `approved=false`), two records are created:

1. **`ml_decision_audit`** with `decision_type='human_override'`, linking to the original decision via `output_details.prev_decision_id`
2. **`audit_logs`** via `log_action()` with `action='OVERRIDE_ML_DECISION'`

This ensures the override is captured in both the ML-specific trail and the general user-action audit trail.

---

## 2. Storage Strategy

### 2.1 Append-only with soft-delete prevention

| Mechanism | Detail |
|---|---|
| **INSERT-only** | No UPDATE or DELETE granted to the application DB user (`artifex`). The `ml_decision_audit` table is write-only from the app layer. |
| **Hash chain** | Each row's `hash` depends on the previous row's `hash`. Tampering with any row breaks all subsequent hashes. Verified by `GET /api/ml-audit/verify`. |
| **Immutable storage** | At weekly cadence, rows older than 90 days are sealed: their JSONB columns are extracted to Parquet files in S3/GCS, and the PostgreSQL rows are replaced with a compressed summary row containing only `hash`, `prev_hash`, and a pointer to the Parquet file path. The hash chain remains intact across the archival boundary. |
| **No DELETE** | If a decision must be retracted (e.g. discovered data leak), append a `RETRACTION` row that references the original decision's `hash` and includes an explanation. The original row is never removed. |

### 2.2 Retention policy

| Age | Storage tier | Accessibility |
|---|---|---|
| 0–90 days | PostgreSQL (`ml_decision_audit`) | Real-time query via API |
| 91 days – 3 years | Parquet in S3/GCS (`s3://artifex-audit/year=2026/month=06/`) | Query via Athena / Presto; API returns `"archived": true` with a signed download URL |
| > 3 years | Glacier / Deep Archive | 72-hour restore; regulatory requests only |

### 2.3 Encryption

- **At rest:** PostgreSQL TDE + S3 server-side AES-256
- **In transit:** TLS 1.3 for all API and database connections
- **Export:** PGP-encrypted per-auditor public key

---

## 3. Query Interface for Compliance Officers

### 3.1 API endpoints

```
GET /api/ml-audit/decisions

  Filters:
    child_id         TEXT         — exact child ID
    decision_type    TEXT         — placement_match | risk_score | crisis_prediction | human_override
    demographic_key  TEXT         — field in child_demographics to filter (e.g. "race")
    demographic_val  TEXT         — value to match (e.g. "Black or African American")
    model_version    TEXT         — exact model version
    min_score        FLOAT        — output_score ≥ N
    max_score        FLOAT        — output_score ≤ N
    from_date        ISO8601      — decided_at ≥
    to_date          ISO8601      — decided_at ≤
    limit            INT (1000)   — page size
    offset           INT (0)      — page offset
    sort             TEXT         — decided_at:desc | output_score:desc | output_score:asc

  Returns:
    {
      "decisions": [ { id, child_id, decision_type, model_version,
                       child_demographics, output_score, output_label,
                       human_overridden, decided_at, hash } ],
      "total": 12450,
      "limit": 1000,
      "offset": 0,
      "archived_rows_available": false
    }

  Example queries:

    # All crisis predictions for children in zip code 606 (South Side Chicago)
    GET /api/ml-audit/decisions?decision_type=crisis_prediction
      &demographic_key=zip_code&demographic_val=606
      &from_date=2026-01-01&to_date=2026-06-01

    # All high-risk decisions (score ≥ 60) for Black children, last quarter
    GET /api/ml-audit/decisions?min_score=60&demographic_key=race
      &demographic_val=Black%20or%20African%20American
      &from_date=2026-03-01&to_date=2026-06-01

    # All human overrides in the last 30 days
    GET /api/ml-audit/decisions?decision_type=human_override
      &from_date=2026-05-01

    # Model version audit — all decisions made by crisis_drift_model_v2.3
    GET /api/ml-audit/decisions?model_version=v2.3&limit=100
```

### 3.2 Integrity verification

```
GET /api/ml-audit/verify

  Returns:
    {
      "valid": true,
      "checked": 38741,
      "broken_links": [],
      "oldest_row": "2025-11-01T00:00:00Z",
      "newest_row": "2026-06-01T06:00:00Z",
      "message": "Hash chain intact — all 38,741 decisions verified"
    }
```

Verification walks the chain in insertion order, recomputing each hash from its predecessor (same algorithm as `GET /api/audit_logs/verify`). A compliance officer can run this on demand before an audit.

### 3.3 CSV / JSON export

```
GET /api/ml-audit/export

  Params: same filters as /decisions + format=csv|json
  Returns: downloadable file with Content-Disposition: attachment

  CSV columns:
    id, child_id, placement_id, decision_type, model_name, model_version,
    decided_at, output_score, output_label, human_overridden, human_decision,
    child_age, child_gender, child_race, child_fpl_percent, child_zip_code,
    feature_hash, hash
```

### 3.4 Dashboard for compliance officers

```
┌────────────────────────────────────────────────────────────────────────┐
│ ╳ ML Decision Audit Trail                              as of Jun 2026 │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  Filter: [decision_type ▼] [demographic_key ▼] [=] [value] [Date range] [Search] │
│                                                                        │
│ ┌──────────────────────────────────────────────────────────────────┐  │
│ │ 38,741 total decisions · Hash chain: ✅ intact · Last 30d: 1,240│  │
│ └──────────────────────────────────────────────────────────────────┘  │
│                                                                        │
│ ┌──────┬──────────┬───────────┬───────┬───────┬────────┬──────────┐  │
│ │ ID   │ Child    │ Type      │ Score │ Model │ Race   │ Override │  │
│ ├──────┼──────────┼───────────┼───────┼───────┼────────┼──────────┤  │
│ │ 38741│ CH-A0427 │ crisis    │ 72.4  │ v2.3  │ Black  │ —        │  │
│ │ 38740│ CH-B1023 │ risk      │ 48.0  │ v2.1  │ White  │ —        │  │
│ │ 38739│ CH-C0512 │ placement │ 81.0  │ v2.3  │ Hispanic│ Rejected│  │
│ │ …    │ …        │ …         │ …     │ …     │ …      │ …        │  │
│ └──────┴──────────┴───────────┴───────┴───────┴────────┴──────────┘  │
│                                                                        │
│                                              [Export CSV] [Verify Chain] │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Bias Drift Detection

### 4.1 Weekly fairness report

A Temporal cron workflow runs every Monday at 03:00 UTC and produces a structured fairness report stored in `fairness_audit_log`:

```sql
CREATE TABLE fairness_audit_log (
    id              SERIAL PRIMARY KEY,
    report_week     DATE        NOT NULL,       -- Monday of the report week
    generated_at    TIMESTAMP   NOT NULL DEFAULT NOW(),
    model_version   TEXT        NOT NULL,

    -- Demographic parity (from ml_decision_audit)
    dp_race         DOUBLE PRECISION,
    dp_ses          DOUBLE PRECISION,
    dp_gender       DOUBLE PRECISION,
    dp_special_needs DOUBLE PRECISION,
    dp_age_group    DOUBLE PRECISION,

    -- Equalized odds (requires prediction_feedback labels)
    fpr_disparity   DOUBLE PRECISION,
    fnr_disparity   DOUBLE PRECISION,

    -- Calibration
    max_ece         DOUBLE PRECISION,

    -- Individual fairness
    consistency     DOUBLE PRECISION,
    nn_disparity    DOUBLE PRECISION,

    -- Historical bias
    bar_race        DOUBLE PRECISION,
    bar_ses         DOUBLE PRECISION,

    -- Alert flags
    flags           JSONB,           -- ["dp_race_exceeded", "bar_amplification", ...]
    overall_status  TEXT             -- PASS | REVIEW | BLOCK
);

CREATE INDEX idx_fairness_week ON fairness_audit_log (report_week DESC);
```

### 4.2 Alert thresholds

| Metric | Amber (warn) | Red (flag) | Consequence |
|---|---|---|---|
| DP (any attribute) | ≥ 0.05 | ≥ 0.10 | Amber: dashboard banner. Red: Slack + email. |
| FPR disparity | ≥ 0.10 | ≥ 0.15 | Amber: log. Red: case-by-case review. |
| FNR disparity | ≥ 0.10 | ≥ 0.20 | Red: immediate model review. Missed crises are critical. |
| BAR (any attribute) | ≥ 1.0 (any) | — | **Red: blocks retraining pipeline.** No new model deployed until signed off. |
| Consistency | ≤ 0.85 | ≤ 0.75 | Red: feature engineering review required. |
| DP_trend | ≥ 0.005/wk × 2 wks | ≥ 0.005/wk × 3 wks | Red: mandatory fairness meeting. |

### 4.3 Alert delivery

| Severity | Channel | Template |
|---|---|---|
| Amber | Dashboard badge + `#fairness` Slack | `⚠️ {metric} entering review — {value} (threshold: {threshold})` |
| Red | Slack + email + PagerDuty (business hours) | `🚨 {metric} violated — {value}. Blocking retrain. Review at {link}` |
| Weekly digest | Email to compliance-officers@ | Full PDF report attached |

### 4.4 Trend tracking

```
GET /api/fairness/trends?metric=dp_race&weeks=24

Returns 24 weekly DP values for race, with:
  - slope (linear regression)
  - 4-week rolling average
  - alert if slope > 0.005/wk
  - sparkline data for chart rendering

Response:
{
  "metric": "dp_race",
  "weeks": 24,
  "values": [0.06, 0.07, 0.06, 0.08, 0.11, 0.14, 0.16, 0.18, ...],
  "slope": 0.011,
  "slope_warning": true,
  "rolling_avg_4wk": 0.15,
  "threshold": 0.005,
  "status": "RED"
}
```

---

## 5. Export Format for External Auditors

### 5.1 Standard export (CSV)

```csv
id,child_id,placement_id,decision_type,model_name,model_version,decided_at_utc,output_score,output_label,output_confidence,human_overridden,human_decision,child_age,child_gender,child_race,child_fpl_percent,child_zip_code,feature_hash,hash,prev_hash
38741,CH-A0427,foster-CH-A0427,crisis_prediction,crisis_drift_model,v2.3,2026-05-28T06:00:00Z,72.4,high,0.82,FALSE,,9,F,Black or African American,85,606,a1b2c3d4,ff1a2b3c,ee0d9e8f
38740,CH-B1023,foster-CH-B1023,risk_score,risk_model,v2.1,2026-05-28T05:30:00Z,48.0,medium,0.74,FALSE,,14,M,White,210,902,d5e6f7a8,9b8c7d6e,1a2b3c4d
38739,CH-C0512,foster-CH-C0512,placement_match,placement_model,v2.3,2026-05-28T04:00:00Z,81.0,high,0.91,TRUE,rejected,6,F,Hispanic or Latino,45,100,b9c0d1e2,3f4e5d6c,7a8b9c0d
```

### 5.2 Full JSON export (per-decision detail, for deep audit)

```json
{
  "export_meta": {
    "generated_at": "2026-06-01T06:00:00Z",
    "generated_by": "compliance-officer@artifex.local",
    "decision_count": 12450,
    "date_range": ["2026-01-01", "2026-06-01"],
    "model_versions": ["v2.1", "v2.3"],
    "hash_chain_verified": true,
    "hash_chain_verified_at": "2026-06-01T06:05:00Z"
  },
  "decisions": [
    {
      "id": 38741,
      "child": {
        "id": "CH-A0427",
        "age": 9,
        "gender": "F",
        "race": "Black or African American",
        "fpl_percent": 85,
        "zip_code": "606",
        "special_needs": true
      },
      "decision": {
        "type": "crisis_prediction",
        "model": { "name": "crisis_drift_model", "version": "v2.3" },
        "input_features": { ... },
        "output": {
          "score": 72.4,
          "label": "high",
          "confidence": 0.82,
          "top_reasons": [
            { "feature": "incident_severity_trend", "shap_value": 14.3 },
            { "feature": "school_attendance_delta", "shap_value": -11.8 }
          ],
          "interventions": [
            "Schedule urgent therapy review",
            "Initiate school liaison meeting"
          ]
        },
        "human_override": false,
        "decided_at": "2026-05-28T06:00:00Z"
      },
      "audit": {
        "hash": "ff1a2b3c...",
        "prev_hash": "ee0d9e8f...",
        "verified": true
      }
    }
  ],
  "hash_chain": {
    "first_hash": "00000000...",
    "last_hash": "ff1a2b3c...",
    "broken_links": []
  }
}
```

### 5.3 Auditor workflow

```
1. Compliance officer authenticates → GET /api/ml-audit/verify
   → "Hash chain intact — 38,741 decisions verified"

2. Officer requests export with filters:
   → GET /api/ml-audit/export?from_date=2026-01-01&decision_type=crisis_prediction&format=csv
   → Server generates CSV, PGP-encrypts with the officer's public key, returns download URL

3. Officer imports CSV into their analysis tool (R / Python / Excel)
   → Computes independent fairness metrics
   → Compares against the weekly fairness reports stored in fairness_audit_log

4. Spot-check: officer picks 10 random hashes from the export
   → GET /api/ml-audit/decisions/{id}/verify
   → Server recomputes hash from stored fields, returns { "hash_matches": true, "input_hash": "ff1a2b3c", "recomputed_hash": "ff1a2b3c" }

5. Annual regulatory submission:
   → Full JSON export + fairness_report_2026_q2.pdf
   → Both PGP-encrypted, delivered via secure file share
   → Retention: 7 years post-placement
```

### 5.4 Auditor verification endpoint

```json
GET /api/ml-audit/decisions/{id}/verify

{
  "id": 38741,
  "hash": "ff1a2b3c...",
  "recomputed_hash": "ff1a2b3c...",
  "prev_hash": "ee0d9e8f...",
  "prev_hash_matches": true,
  "verification": "PASS",
  "audited_at": "2026-06-01T06:10:00Z",
  "auditor_user_id": "auditor@agency.gov"
}
```

---

## 6. Implementation Plan

### Migration 0005: `ml_decision_audit` table

```sql
-- Full DDL as specified in §1.2
-- Plus trigger that auto-computes the hash on INSERT (avoids app-layer bugs)

CREATE OR REPLACE FUNCTION compute_ml_decision_hash()
RETURNS TRIGGER AS $$
DECLARE
  last_hash TEXT;
BEGIN
  SELECT COALESCE(
    (SELECT hash FROM ml_decision_audit ORDER BY id DESC LIMIT 1),
    '0' * 64
  ) INTO last_hash;
  NEW.prev_hash := last_hash;
  NEW.hash := encode(
    sha256(
      (last_hash || '|' || NEW.decision_type || '|' ||
       NEW.child_id || '|' || NEW.decided_at::text || '|' ||
       COALESCE(NEW.output_score::text, '') || '|' ||
       COALESCE(NEW.model_version, ''))::bytea
    ), 'hex'
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_ml_decision_audit_hash
  BEFORE INSERT ON ml_decision_audit
  FOR EACH ROW
  EXECUTE FUNCTION compute_ml_decision_hash();
```

### Logging integration points

| Existing code | Insert point |
|---|---|
| `api/services/crisis_predictor.py` `predict_and_store()` | After `INSERT INTO crisis_predictions`, insert `ml_decision_audit` with decision_type=`crisis_prediction` |
| `workflows/temporal_worker.py` `compute_risk_activity()` | After risk score is computed, insert with decision_type=`risk_score` |
| `services/placement_recommender.py` `rank_families()` | After families are ranked, insert with decision_type=`placement_match` |
| `api/routes/placements.py` `approve_placement()` | If overridden (rejected), insert with decision_type=`human_override` |

### Pipeline ownership

| Component | Owner |
|---|---|
| `ml_decision_audit` table creation | Platform (Alembic migration 0005) |
| INSERT calls in model services | ML engineering |
| Query API (`GET /api/ml-audit/*`) | Backend API |
| Weekly fairness workflow | ML engineering + Platform |
| Compliance dashboard UI | Frontend |
| External auditor export format | Legal / Compliance + Engineering |
