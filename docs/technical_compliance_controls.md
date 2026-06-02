# Technical Compliance Controls — HIPAA / GDPR

---

## 1. Encryption — At Rest and In Transit

### Where Encryption Lives in the Stack

```
                  ┌──────────────────────────────────────┐
                  │  TLS 1.3  (ALB + cert-manager)       │
                  │                                      │
     Client ─────▶│  ALB terminates TLS                  │────▶ API Pod
     (HTTPS)      │  cipher: TLS_AES_256_GCM_SHA384      │      (HTTP localhost)
                  │  cert: ACM / LetsEncrypt             │
                  └──────────────────────────────────────┘

                  ┌──────────────────────────────────────┐
                  │  gRPC+TLS   (Temporal / NATS)        │
                  │                                      │
     API Pod ────▶│  Temporal gRPC: mTLS (cert per pod)  │────▶ Temporal Server
     Worker Pod   │  NATS: TLS 1.3 with client cert      │────▶ NATS Cluster
                  └──────────────────────────────────────┘

                  ┌──────────────────────────────────────┐
                  │  AES-256   (at rest layers)          │
                  │                                      │
                  │  ┌─ EBS volume encryption (RDS/NATS) │
                  │  │   KMS key: alias/artifex-ebs      │
                  │  ├─ RDS TDE (Transparent Data Enc)   │
                  │  │   KMS key: alias/artifex-rds      │
                  │  ├─ pg_crypto column-level           │
                  │  │   For PHI columns (diagnosis,     │
                  │  │   prescriptions, therapy_notes)   │
                  │  ├─ S3 SSE-S3 or SSE-KMS             │
                  │  │   For exports, backups, tiles     │
                  │  └── Backups (RDS snapshots +        │
                  │       S3 cross-region replicas)      │
                  └──────────────────────────────────────┘
```

### Layer-by-layer implementation

| Layer | Mechanism | Key / Cert management | Performance impact |
|-------|-----------|-----------------------|-------------------|
| **TLS termination** | AWS ALB with TLS 1.3 listener, `TLS_AES_256_GCM_SHA384` cipher suite | ACM (auto-renewal) or cert-manager for LetsEncrypt in non-AWS deployments | Negligible — ALB offloads TLS |
| **Pod-to-pod (sidecar)** | Linkerd or Istio mTLS between API pods, worker pods, and Message Bus | SPIRE or cert-manager CSI driver; cert rotation every 24 h | ~3–5 % CPU overhead (mTLS per request) |
| **NATS** | NATS TLS 1.3 with client certificate auth | PEM per node, rotated weekly; NATS config `tls { cert_file, key_file, ca_file }` | Negligible — NATS is async |
| **Temporal gRPC** | mTLS via Temporal's `tls` client config block | Client and server certs from same CA; Temporal server `--tls-cert-file` / `--tls-key-file` | Negligible — gRPC framing |
| **RDS at rest** | AES-256 (RDS TDE) with KMS key rotation every 12 months | KMS `kms:Decrypt` only granted to the RDS instance role | <3 % latency overhead |
| **PHI column encryption** | `pgp_sym_encrypt` / `pgp_sym_decrypt` in PostgreSQL using a column-level key stored in AWS Secrets Manager | Encrypt via `pgp_sym_encrypt(text, current_setting('phi.encryption_key'))` set at session start from Secrets Manager | 5–15 % per PHI column write; implement only on `diagnosis`, `prescriptions`, `therapy_notes` |
| **S3 objects** | SSE-S3 (AES-256) for standard exports; SSE-KMS for logs containing PHI | KMS key `alias/artifex-s3-phi` for PHI-containing objects | No client-side impact (S3 transparent) |
| **RDS snapshots** | AES-256 (inherits from RDS TDE) | Same KMS key as RDS | No impact |

### Database pattern for column-level PHI encryption

```sql
-- Session setup (called once per connection, key fetched from Secrets Manager)
SET SESSION phi.encryption_key TO 'decrypted-key-from-secrets-manager';

-- Write (with integrity check — separate IV per row via default gen_random_bytes)
UPDATE medical_events
SET diagnosis = pgp_sym_encrypt($1, current_setting('phi.encryption_key'))
WHERE id = $2;

-- Read (only for caseworkers with explicit "medical history review" purpose)
SELECT pgp_sym_decrypt(diagnosis, current_setting('phi.encryption_key')) AS diagnosis
FROM medical_events
WHERE id = $1;

-- Note: the purpose_code 'medical_history_review' must be logged in audit_logs
-- before the session key is set.  See audit-logging section below.
```

Indexes cannot be built directly on encrypted columns. Where querying is needed (e.g., "find all children with diagnosis X"), a deterministic HMAC column (`hmac(text, key, 'sha256')`) serves as a searchable hash:

```sql
ALTER TABLE medical_events ADD COLUMN diagnosis_search_hash BYTEA;
UPDATE medical_events
SET diagnosis_search_hash = hmac(diagnosis, current_setting('phi.search_key'), 'sha256');

-- Query
SELECT * FROM medical_events
WHERE diagnosis_search_hash = hmac('F43.10', current_setting('phi.search_key'), 'sha256');
```

---

## 2. Role-Based Access Control (RBAC)

### Role Hierarchy

```
                        ┌──────────────────────┐
                        │  System Admin         │  No data access
                        │  (deploy, infra, DB   │  Full infrastructure
                        │   migration, no PHI)  │
                        └──────────────────────┘

                        ┌──────────────────────┐
                        │  Read-Only Auditor    │  Log-only access
                        │  (audit_logs,         │  Can verify hash chain
                        │   ml_decision_audit,  │  Cannot read PHI payloads
                        │   no PHI columns)     │
                        └──────────────────────┘

                        ┌──────────────────────┐
                        │  Compliance Officer   │  Privacy + compliance
                        │  (privacy exports,    │  Can execute erasure
                        │   erasure requests,   │  Can view any record
                        │   DPIA docs)          │  with "compliance" purpose
                        └──────────────────────┘

                        ┌──────────────────────┐
                        │  Director             │  Cross-org view
                        │  (aggregate dashboards│  Cannot view individual PHI
                        │   fairness metrics,   │  Can override interventions
                        │   geo maps, no PHI)   │
                        └──────────────────────┘

                        ┌──────────────────────┐
                        │  Supervisor           │  Approval authority
                        │  (verify events,      │  Can view PHI in their unit
                        │   approve scenarios,  │  Can override decisions
                        │   manage team)        │
                        └──────────────────────┘

                        ┌──────────────────────┐
                        │  Caseworker           │  Front-line
                        │  (assigned cases only,│  CRUD on own children
                        │   view PHI, run sims) │  Cannot verify/seal
                        └──────────────────────┘
```

### Permission matrix

| Resource | Caseworker | Supervisor | Director | Compliance | Read-Only Auditor | System Admin |
|----------|-----------|------------|----------|------------|-------------------|--------------|
| Children (own cases) | CRUD | CRUD | Read (aggregate) | Read (all) | — | — |
| Children (other cases) | — | Read | Read (aggregate) | Read (all) | — | — |
| PHI columns | Read (own) | Read (unit) | — | Read (all, logged) | — | — |
| Audit logs | Own actions | Unit actions | All (no PHI) | All | All (no PHI) | — |
| ml_decision_audit | Read own | Read unit | Read all | Read all | Read all (no features) | — |
| Fairness metrics | — | Read | Read | Read | Read | — |
| Twin simulate | Own children | Own unit | Read-only | — | — | — |
| Verify/seal events | — | Execute | — | Execute | — | — |
| Approve placements | — | Execute | — | — | — | — |
| Privacy export | — | — | — | Execute | — | — |
| Erasure request | Initiate | Approve | — | Co-sign | — | — |
| Infrastructure | — | — | — | — | — | Full |
| User management | — | Own team | All users | — | — | All users |

### Implementation via FastAPI dependency chain

```python
# api/auth.py — role hierarchy with implied permissions

ROLE_HIERARCHY = {
    "caseworker":       0,
    "supervisor":       1,
    "director":         2,
    "compliance":       3,
    "readonly_auditor": 4,
    "admin":            5,
}

# Role-based dependency
def require_role(*roles: str) -> Callable:
    """Require the authenticated user to have one of the given roles."""
    async def dep(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="Insufficient role")
        return user
    return dep

# Hierarchy-based access (a supervisor can do what a caseworker can)
def min_role(level: int) -> Callable:
    """Require role level >= level (0=caseworker ... 5=admin)."""
    async def dep(user: dict = Depends(get_current_user)) -> dict:
        if ROLE_HIERARCHY.get(user["role"], -1) < level:
            raise HTTPException(status_code=403, detail="Insufficient role level")
        return user
    return dep

# Scoped access — caseworkers can only access their assigned children
async def get_child_or_forbidden(
    child_id: str,
    user: dict = Depends(get_current_user),
    pool = Depends(get_pool),
) -> dict[str, Any]:
    """Returns the child row only if the user is authorised."""
    row = await pool.fetchrow(
        "SELECT * FROM children WHERE child_id = $1", child_id
    )
    if not row:
        raise HTTPException(404)

    # System admin and compliance can access any child (with audit)
    if user["role"] in ("admin", "compliance", "readonly_auditor"):
        return dict(row)

    # Director: aggregate-only, cannot read individual profiles
    if user["role"] == "director":
        raise HTTPException(403, detail="Directors cannot view individual records")

    # Supervisor: any child in their unit
    if user["role"] == "supervisor":
        if row.get("unit_id") in user.get("unit_ids", []):
            return dict(row)
        raise HTTPException(403, detail="Child not in your unit")

    # Caseworker: only assigned cases
    if user["role"] == "caseworker":
        assigned = await pool.fetchval(
            "SELECT 1 FROM placements WHERE child_id = $1 AND caseworker_id = $2",
            child_id, user["user_id"],
        )
        if assigned:
            return dict(row)
        raise HTTPException(403, detail="Child not in your caseload")

    raise HTTPException(403)
```

---

## 3. Audit Logging

### What Events Are Logged

Every row in `audit_logs` has a `action` field from a controlled vocabulary:

| Category | Actions | PHI flag |
|----------|---------|----------|
| **Placement** | `VIEW_PLACEMENT`, `CREATE_PLACEMENT`, `UPDATE_PLACEMENT`, `APPROVE_PLACEMENT` | Yes (if child_id present) |
| **PHI access** | `VIEW_PHI`, `EXPORT_PHI`, `PRINT_PHI` | Yes |
| **ML decisions** | `CRISIS_PREDICTION`, `RISK_SCORE`, `PLACEMENT_MATCH`, `COUNTERFACTUAL_SIM` | Yes |
| **Privacy** | `EXPORT_PRIVACY`, `ERASURE_REQUEST`, `ERASURE_EXECUTE`, `RESTRICT_PROCESSING` | Yes |
| **RBAC** | `USER_CREATE`, `USER_ROLE_CHANGE`, `USER_DEACTIVATE`, `PURPOSE_CODE_USE` | No |
| **System** | `MIGRATION_RUN`, `CONFIG_CHANGE`, `BACKUP_START`, `BACKUP_COMPLETE` | No |
| **Export** | `EXPORT_CSV`, `EXPORT_PDF`, `EXPORT_GEOJSON` | Yes (link to PHI log) |
| **Erasure** | `ERASURE_COOLING_START`, `ERASURE_EXECUTED`, `ERASURE_DENIED` | Yes |

### Log Format

```json
{
  "id": "evt_abcd1234",
  "timestamp": "2026-06-01T14:30:00.000Z",
  "user_id": "caseworker@artifex.local",
  "user_role": "caseworker",
  "action": "VIEW_PHI",
  "resource_type": "medical_events",
  "resource_id": "42",
  "child_id": "CH-A0427",
  "purpose_code": "medical_history_review",
  "phi_access": true,
  "request_id": "req_xyz789",
  "ip_address": "203.0.113.42",
  "user_agent": "Mozilla/5.0 ...",
  "session_id": "sess_456",
  "outcome": "success",
  "detail": {
    "columns_accessed": ["diagnosis", "prescriptions"],
    "encryption_key_used": true
  },
  "previous_hash": "0000abcd...",
  "hash": "sha256(timestamp + user_id + action + previous_hash)"
}
```

### Tamper Evidence — Hash Chain

The `audit_logs` table uses the same SHA-256 hash chain pattern as `ml_decision_audit`:

```sql
-- Trigger function (applied on INSERT only — audit logs are append-only)

CREATE OR REPLACE FUNCTION compute_audit_hash() RETURNS trigger AS $$
DECLARE
  prev_hash TEXT;
BEGIN
  SELECT COALESCE(
    (SELECT hash FROM audit_logs ORDER BY id DESC LIMIT 1),
    '0000000000000000000000000000000000000000000000000000000000000000'
  ) INTO prev_hash;

  NEW.hash := encode(
    sha256(
      (NEW.timestamp::TEXT || NEW.user_id || NEW.action || prev_hash)::BYTEA
    ),
    'hex'
  );
  NEW.previous_hash := prev_hash;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_audit_hash
  BEFORE INSERT ON audit_logs
  FOR EACH ROW EXECUTE FUNCTION compute_audit_hash();
```

**Verification query** (run by Read-Only Auditor weekly):

```sql
SELECT
  COUNT(*) AS total_rows,
  BOOL_AND(
    (SELECT hash FROM audit_logs AS prev WHERE prev.id = a.id - 1) =
    a.previous_hash
    OR a.id = 1
  ) AS chain_intact
FROM audit_logs AS a;
```

### Retention Period

| Regulation | Requirement | Artifex policy |
|------------|-------------|----------------|
| **HIPAA** | 6 years (§164.316(b)(2)) | 7 years |
| **GDPR** | No more than necessary (Art 5(1)(e)) | 7 years, then aggregated |
| **NY SHIELD Act** | 6 years for security breaches | 7 years |
| **NY 18 NYCRR 428.10** | 6 years after case closure (10 if foster care) | Match child record retention |

**Implementation:**

```sql
-- Partition audit_logs by month for efficient archival
CREATE TABLE audit_logs ( ... ) PARTITION BY RANGE (timestamp);

-- Monthly archival job (runs via Temporal cron on day 1):
-- 1. COPY rows older than 7 years to audit_logs_archived (compressed CSV in S3)
-- 2. DROP the partition
-- 3. Retain hash-chain proof (merkle root of archived partition in a separate table)
```

---

## 4. Data Residency — Multi-Tenant Architecture

### Architecture: Database-per-region, schema-per-tenant

```
EU region (eu-west-1)                  US region (us-east-1)
┌──────────────────────────┐          ┌──────────────────────────┐
│  RDS Cluster (artifex-eu) │          │  RDS Cluster (artifex-us)│
│  ┌────────────────────┐   │          │  ┌────────────────────┐  │
│  │ tenant_eu_agency_1  │   │          │  │ tenant_us_agency_1  │  │
│  │ tenant_eu_agency_2  │   │          │  │ tenant_us_agency_2  │  │
│  └────────────────────┘   │          │  └────────────────────┘  │
│  KMS: eu-west-1 key       │          │  KMS: us-east-1 key      │
│  Backup: eu-west-1 only   │          │  Backup: us-east-1 + dr  │
└──────────────────────────┘          └──────────────────────────┘

          ▲                                  ▲
          │                                  │
          │  Global API Gateway               │
          │  (tenant_id → region routing)     │
          │                                   │
┌─────────┴───────────────────────────────────┴──────────┐
│  Application Pods (kubernetes)                         │
│  - EU pods in eu-west-1a,b                              │
│  - US pods in us-east-1a,b                              │
│  - No cross-region DB traffic                           │
│  - Data-plane read replicas in same region               │
└────────────────────────────────────────────────────────┘
```

### Tenant routing logic

```python
# api/dependencies.py

TENANT_REGION_MAP: dict[str, str] = {
    "london-borough": "eu-west-1",
    "essex-county":   "eu-west-1",
}

REGION_POOLS: dict[str, asyncpg.Pool] = {}  # populated at startup

async def get_pool_for_tenant(tenant_id: str) -> asyncpg.Pool:
    region = TENANT_REGION_MAP.get(tenant_id, "us-east-1")
    return REGION_POOLS[region]

# Middleware that extracts tenant_id from JWT or subdomain
async def tenant_middleware(request: Request, call_next):
    tenant_id = request.headers.get("X-Tenant-Id") or extract_from_subdomain(request.url.hostname)
    request.state.tenant_id = tenant_id
    request.state.pool = await get_pool_for_tenant(tenant_id)
    return await call_next(request)
```

### What never crosses regions

| Data type | EU region | US region |
|-----------|-----------|-----------|
| EU tenant RDS data | Stays in eu-west-1 | Never replicated |
| PHI columns | eu-west-1 KMS key | — |
| ML training data (pseudonymised) | Trained in eu-west-1; model artefact in eu-west-1 S3 | Trained in us-east-1 |
| Logs (CloudWatch) | Log group in eu-west-1 | Log group in us-east-1 |
| Backups (RDS snapshots) | eu-west-1 only | us-east-1 + us-west-2 (DR) |
| Support exports | Customer chooses region at export time | Customer chooses region |

### SCC (Standard Contractual Clauses) gate

If an EU agency explicitly authorises US processing (e.g., for cross-border foster placement), the tenant is flagged in `TENANT_REGION_MAP` as `"us-east-1"` and an SCC is digitally executed before the first write:

```python
TENANT_REGION_MAP: dict[str, str] = {
    "london-borough":    "eu-west-1",
    "berlin-jugendamt":  "eu-west-1",
    "eu-agency-explicit": "us-east-1",  # SCC on file, TIA completed
}
```

---

## 5. Right to Erasure (GDPR Art 17)

### The Conflict

A child in foster care requests erasure of their data. However:
- **NY 18 NYCRR 428.10** requires retention until 6 years after case closure
- **HIPAA §164.316(b)(2)** requires retention for 6 years
- **Mandated reporting laws** require the agency to maintain records of abuse/neglect investigations
- The child's own safety may depend on case history (e.g., known triggers, medication allergies)

Artifex cannot hard-delete. Instead, it implements a **three-stage erasure pipeline** that satisfies the "right to be forgotten" by making data inaccessible to normal operations while preserving it for legal retention.

### Stage 1 — Restriction (Art 18) — same day

```sql
-- 1. Set restriction flag — all ML pipelines skip this child
UPDATE children
SET data_subject_restricted = TRUE,
    restriction_reason = 'GDPR Art 18 / deletion request pending',
    restricted_at = NOW(),
    restricted_by = 'compliance-officer@agency.gov',
    restriction_cooling_end = NOW() + INTERVAL '30 days'
WHERE child_id = 'CH-A0427';

-- 2. ML model inference skip (checked at query time)
-- crisis_predictor.py:
SELECT data_subject_restricted FROM children WHERE child_id = $1
-- if TRUE → return 423 Locked

-- 3. UI hides the child from all caseworker views
-- A banner is shown: "This child's data is restricted — contact compliance"
```

### Stage 2 — Cooling-off (30 days)

During cooling-off:
- Supervisor and Compliance Officer review the request
- If any legal retention obligation exists → erasure is **denied**, restriction stays **permanent**
- If no retention obligation exists → erasure proceeds at day 30

```sql
-- Permanent restriction (denied erasure)
UPDATE children
SET data_subject_restricted = TRUE,
    restriction_reason = 'Legal retention obligation — NY 18 NYCRR 428.10',
    erasure_denied = TRUE,
    erasure_denied_at = NOW(),
    erasure_denied_by = 'supervisor@agency.gov',
    erasure_denied_reason = 'Records needed for sibling reunification planning'
WHERE child_id = 'CH-A0427';

-- Log the denial (audit)
INSERT INTO erasure_requests
    (child_id, requested_at, requested_by, cooling_end, status, denied_reason, denied_by)
VALUES
    ('CH-A0427', NOW(), 'compliance@agency.gov', NOW(), 'denied',
     'Legal retention obligation — NY 18 NYCRR 428.10', 'supervisor@agency.gov');
```

### Stage 3 — Erasure Execution (day 31, if approved)

Artifex **never hard-deletes rows**. It replaces PII with `[REDACTED]` and preserves non-PII data needed for aggregate statistics and audit integrity.

```sql
-- Transaction block (all or nothing)
BEGIN;

-- 1. Null all PII in children table
UPDATE children
SET first_name = '[REDACTED PURSUANT TO GDPR ART 17]',
    last_name  = '[REDACTED PURSUANT TO GDPR ART 17]',
    school     = NULL,
    zip_code   = NULL,
    race       = NULL,
    fpl_percent = NULL,
    data_subject_erased = TRUE,
    erased_at = NOW(),
    erased_by = 'compliance@agency.gov'
WHERE child_id = 'CH-A0427';

-- 2. Null PII in medical_events (but keep row count for stats)
UPDATE medical_events
SET diagnosis      = NULL,
    prescriptions  = NULL,
    provider_name  = NULL,
    notes          = '[REDACTED]'
WHERE child_id = 'CH-A0427';

-- 3. Null features in ML audit (preserve audit chain)
UPDATE ml_decision_audit
SET input_features    = '{"erased": true}'::jsonb,
    child_demographics = '{"erased": true}'::jsonb,
    output_details    = output_details || '{"erased_pii": true}'::jsonb
WHERE child_id = 'CH-A0427';
-- Hash chain is NOT recomputed — previous hashes remain valid.

-- 4. Null twin state features
UPDATE child_twin_states
SET current_features = '{"erased": true}'::jsonb,
    outcome_probs    = NULL,
    pending_simulations = NULL
WHERE child_id = 'CH-A0427';

-- 5. Preserve behavioural_drift_signals (aggregate stats only)
UPDATE behavioural_drift_signals
SET signals_json = '{"erased": true}'::jsonb
WHERE child_id = 'CH-A0427';

-- 6. Write erasure record
INSERT INTO erasure_requests
    (child_id, requested_at, cooling_end, executed_at, executed_by, status)
VALUES
    ('CH-A0427',
     (SELECT requested_at FROM erasure_requests WHERE child_id = 'CH-A0427' ORDER BY requested_at LIMIT 1),
     NOW() - INTERVAL '1 day',
     NOW(), 'compliance@agency.gov',
     'executed');

COMMIT;
```

### What remains after erasure

| Table | After erasure | Purpose |
|-------|---------------|---------|
| `children` | Row exists, PII nulled, `data_subject_erased = TRUE` | Aggregate counts, retention proof |
| `placements` | Row exists, child_id preserved (but no PII join possible) | Placement duration statistics |
| `crisis_predictions` | Prediction scores preserved | Model fairness monitoring |
| `ml_decision_audit` | Features nulled, hash chain intact | Audit integrity verification |
| `child_twin_states` | Features nulled, row preserved | Count of twin states |
| `audit_logs` | Unchanged (no PII in audit logs by design) | Tamper-proof log |
| `erasure_requests` | Full record of the erasure event | Compliance audit |

### Automated verification

```python
# Temporal workflow: erasure_verification_workflow.py
# Runs weekly, verifies that erased children have no PII accessible

async def verify_erasure_integrity(child_id: str) -> dict:
    """Query each table and confirm no PII is accessible."""
    checks = {
        "children": f"SELECT first_name FROM children WHERE child_id = '{child_id}'",
        "medical_events": f"SELECT diagnosis FROM medical_events WHERE child_id = '{child_id}' LIMIT 1",
        "child_life_events": f"SELECT payload FROM child_life_events WHERE child_id = '{child_id}' LIMIT 1",
    }
    results = {}
    for table, query in checks.items():
        row = await pool.fetchrow(query)
        val = str(row[0]) if row else None
        if val and "[REDACTED" not in val and val != "None":
            results[table] = "FAIL — PII still present"
            # Alert compliance officer
        else:
            results[table] = "PASS"
    return results
```

---

## Summary of AWS Services Used

| Control | AWS service | Configuration |
|---------|-------------|---------------|
| TLS termination | ALB + ACM | TLS 1.3, `TLS_AES_256_GCM_SHA384` |
| EBS encryption | KMS + EBS | `alias/artifex-ebs`, automatic for all volumes |
| RDS encryption | KMS + RDS TDE | `alias/artifex-rds`, enabled at creation |
| Column encryption | Secrets Manager + pg_crypto | Key in Secrets Manager, rotated every 90 days |
| S3 encryption | SSE-S3 / SSE-KMS | `alias/artifex-s3-phi` for PHI objects |
| Data residency | RDS multi-region, S3 bucket per region | No cross-region replication for PHI |
| Audit log archival | S3 Glacier (7+ year retention) | Lifecycle policy on `audit-logs-archive` bucket |
| Encryption key rotation | KMS automatic (annual) + Secrets Manager (90 day) | CloudWatch event triggers Lambda rotation |
