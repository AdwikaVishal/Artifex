# ARTIFEX — Migrate from Mock Data to Real-Time PostgreSQL Architecture

This document is the **end-to-end implementation plan** to eliminate mock/demo data and make every workflow, recommendation, ML inference, and dashboard update come from **live PostgreSQL records**.

## Non‑negotiable invariants

1. **Workflow inputs carry only identifiers** (e.g., `child_id`, `workflow_id`) — never the full child profile.
2. **No hardcoded families / children / capacity** in runtime code paths.
3. **No fallback recommendations** (no “unknown”, no “MANUAL_REVIEW” fake family).  
   If a recommendation cannot be produced, emit an explicit **status**: `needs_manual_review`.
4. **All dashboard state is DB-derived** (or errors if DB is unreachable).

---

## Target architecture (runtime)

```mermaid
flowchart LR
  subgraph UI[React Dashboard]
    UI1[Child Intake / Child Profile]
    UI2[Family Mgmt / Capacity]
    UI3[Workflow Tracking / Live Placements]
  end

  subgraph API[FastAPI API]
    REST[REST: /children /families /placements]
    WS[WebSocket: /ws/dashboard]
    EVT[Event ingest: POST /events]
  end

  subgraph DB[(PostgreSQL)]
    CH[(children)]
    FA[(families)]
    AP[(active_placements)]
    PH[(placement_history)]
    PP[(placement_predictions)]
    WE[(workflow_events)]
    WS2[(workflow_status)]
  end

  subgraph Temporal[Temporal Worker]
    WF[FosterPlacementWorkflow]
    ACT[Activities: load→features→infer→rank→store→publish→capacity]
  end

  subgraph NATS[NATS]
    N1[foster.placements]
    N2[foster.workflow_events]
    N3[events.live.*]
  end

  UI -->|REST| REST
  UI -->|WS| WS
  REST --> DB
  EVT --> NATS
  WF -->|Activities| ACT
  ACT --> DB
  ACT -->|publish| NATS
  NATS -->|push| WS
```

---

# Phase-by-phase plan (1–12)

## Phase 1 — Complete mock/demo data audit (DONE in repo)

Deliverable:
- `mock_data_audit.md`: repo-wide scan with **file / symbol / line / marker / replacement strategy**.

Removal policy:
- Delete demo datasets + synthetic seed scripts.
- Remove heuristic fallback recommendation logic.

## Phase 2 — Real child intake system

### Database (children)
Target columns (extend existing `children` table as needed):
- `child_id (PK)`, `first_name`, `age`, `gender`, `location`
- `sibling_group`, `special_needs`, `medical_needs`, `behavioral_support`
- `emergency_level`, `case_notes`, `created_at`, `updated_at`

### API (already present; must remain DB-backed)
- `POST /children`
- `GET /children`
- `GET /children/{child_id}`
- `PUT /children/{child_id}`
- `DELETE /children/{child_id}`

### Workflow contract
- Workflow input: `{ "child_id": "…" }`
- Activity reads: `SELECT * FROM children WHERE child_id=$1`

## Phase 3 — Real foster family management

### Database (families)
Target columns (extend existing `families` table as needed):
- `family_id (PK)`, `name`, `location`
- `total_capacity`
- `experience_level`
- `languages TEXT[]`
- `special_needs_trained`, `sibling_group_capable`
- `active BOOLEAN`
- `created_at`

### API (already present; must remain DB-backed)
- `POST /families`
- `GET /families`
- `GET /families/{id}`
- `PUT /families/{id}`
- `DELETE /families/{id}`

### “Available families” query (canonical)
```sql
SELECT *
FROM families
WHERE active = TRUE
  AND (
    total_capacity - (
      SELECT COUNT(*)
      FROM active_placements ap
      WHERE ap.family_id = families.family_id
        AND ap.status = 'active'
    )
  ) > 0;
```

## Phase 4 — Real capacity tracking

Canonical rule:
- **Do not store** mutable `available_capacity` as a source of truth.
- Always derive it from `total_capacity - active_placements(active)`.

State changes:
- `Placement Approved` → insert active_placements row (status=active)
- `Placement Ended/Closed` → set active_placements.status=closed and write placement_history
- `Placement Cancelled` → set status=cancelled (and optionally write history)

## Phase 5 — Historical data collection (placement_history)

Data rules:
- Only write to `placement_history` when a placement completes or disrupts.
- Populate `duration_days` server-side for consistency.

## Phase 6 — Real ML training pipeline

Training datasets (all from Postgres):
- `children`, `families`, `placement_history`, `active_placements`

Models:
- Placement success model (recommended): **XGBoost/LightGBM/CatBoost** classifier on (child,family) pairs.
- Optional disruption model: classifier on placement_history outcomes.

Outputs (persisted):
- `probability_of_success`, `risk_score`, `confidence_score`, `model_version`, `feature_importance`

## Phase 7 — Recommendation engine

Canonical pipeline:
1. Load child (`children`)
2. Load available families (computed capacity)
3. Generate pair features
4. Run ML inference for each family
5. Rank families
6. Store prediction (`placement_predictions`)
7. Return top matches

Contract:
```json
{
  "recommended_family": { "family_id": "...", "name": "..." },
  "match_score": 92,
  "confidence_score": 0.94,
  "risk_score": 0.08,
  "top_matches": []
}
```

## Phase 8 — Temporal workflow redesign

New activity chain:
1. `load_child_profile_activity(child_id)`
2. `load_available_families_activity(child_id)`
3. `generate_features_activity(child, families)`
4. `run_ml_inference_activity(features)`
5. `rank_families_activity(inference)`
6. `store_prediction_activity(workflow_id, child_id, ranked)`
7. `publish_match_activity(payload)`
8. `update_capacity_activity(workflow_id, child_id, family_id, status)`

Failure semantics:
- If no recommendation possible → publish status `needs_manual_review` (not a fake family).

## Phase 9 — Real-time dashboard

Dashboard views must be fully DB-backed:
- live children
- live families + computed capacity
- live placements
- latest predictions
- workflow timeline + status

## Phase 10 — Live event streaming

Pipeline:
Temporal → NATS → API WebSocket fanout → React

Event types (minimum):
- `Child Created`
- `Family Updated`
- `Capacity Changed`
- `Prediction Generated`
- `Placement Approved`
- `Placement Closed`
- `Risk Alert`

## Phase 11 — Data validation / health checks

Automated checks (API endpoint + script):
```sql
SELECT COUNT(*) FROM children;
SELECT COUNT(*) FROM families;
SELECT COUNT(*) FROM placement_history;
SELECT COUNT(*) FROM placement_predictions;
```

Operational checks:
- DB connectivity
- Temporal connectivity
- NATS connectivity
- Worker liveness

## Phase 12 — Final deliverable checklist

1. Architecture diagram (this doc)
2. DB migrations (preferred: dedicated migration runner or Alembic)
3. APIs: children/families/placements/predictions
4. Temporal workflow + activities
5. ML training + inference artifacts + model registry/versioning
6. React dashboard pages wired to live endpoints + WebSocket
7. NATS subjects + schema
8. WebSocket push + reconnect/backfill strategy
9. Testing plan
10. Deployment checklist

---

## Testing plan (minimum)

1. **API contract tests** for `/children` and `/families` CRUD.
2. **Workflow integration test**: create child + create family + start workflow → prediction stored → placement published.
3. **Capacity invariants**: approve placement reduces computed capacity; close restores.
4. **No-mock enforcement**: CI step that runs the audit and fails if new hardcoded demo markers are introduced.

## Deployment checklist (minimum)

- [ ] DB migrations applied
- [ ] Model artifacts present (placement_model + features)
- [ ] Temporal worker deployed with same schema expectations as API
- [ ] NATS subjects/ACLs configured
- [ ] API WebSocket enabled behind ingress
- [ ] Observability: logs + metrics + traces

