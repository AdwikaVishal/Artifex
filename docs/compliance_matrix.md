# Compliance Matrix — Artifex

## Scope

Artifex stores, processes, and transmits:
- Demographics, case notes, court orders, and placement history for children in foster care
- Health records (immunisations, diagnoses, medications, therapy notes)
- Education records (school enrolment, IEPs, attendance)
- Family and caseworker information (addresses, background checks, home study reports)
- ML-derived risk scores, drift indices, behavioural signals, and simulation outputs

---

## 1. HIPAA (US — Health Insurance Portability and Accountability Act)

### Does Artifex Have to Comply?

Child welfare agencies that bill Medicaid for health services (therapy, psychiatric medication management, developmental screenings) are **covered entities**. Artifex as their SaaS provider is a **business associate** and must sign BAAs. Even agencies that do not bill Medicaid still handle health data that intersects with HIPPA via state child welfare mandates — the safe position is HIPAA compliance for all health-related fields.

| Category | Detail |
|----------|--------|
| **Applicable data** | `medical_events.diagnosis`, `medical_events.prescriptions`, `therapy_session` notes, `children` special_needs flag, crisis_predictions (if derived from health data), any payload with ICD codes or DSM diagnoses |
| **Required technical controls** | • **Access control** (§164.312(a)(1)) — role-based access (caseworker / supervisor / admin / ML-system), each PHI access logged to `audit_logs` with `action = "VIEW_PHI"` and `target_type = "child"`<br>• **Encryption at rest** — AES-256 for PostgreSQL (PGP `pgp_sym_encrypt` for PHI columns or column-level encryption via pg_crypto), S3 SSE-S3 for exports<br>• **Encryption in transit** — TLS 1.3 for all API, NATS, and Temporal gRPC connections<br>• **Automatic logoff** — session timeout after 30 min inactivity (enforced in `AuthContext.tsx`)<br>• **Integrity controls** — `ml_decision_audit` SHA-256 hash chain (§164.312(c)(2)) |
| **Required policy controls** | • **BAA** executed with every agency customer before production access<br>• **Minimum necessary policy** — default SQL views exclude PHI columns; caseworker must affirm a reason (e.g., "medical history review") to unlock the `medical_events` payload; all non-PHI dashboards (fairness, twin) operate on de-identified aggregates<br>• **Breach notification procedure** — 60-day clock starts at discovery; automated alert to security officer when `audit_logs` detects anomalous PHI access (5+ children viewed in 10 min by a single user)<br>• **Sanction policy** — termination + mandatory reporting for intentional PHI snooping |
| **Audit evidence** | • BAA inventory (signed, dated)<br>• Access logs with user_id, timestamp, child_id, action, PHI flag (query: `SELECT * FROM audit_logs WHERE phi_access = TRUE AND timestamp > NOW() - INTERVAL '90 days'`)<br>• Breach drill records (twice-yearly tabletop)<br>• Minimum-necessary configuration review (quarterly) |

---

## 2. GDPR (EU — General Data Protection Regulation)

### Lawful Basis

Artifex processes data under **Article 6(1)(e) — public task** (child protection is a task carried out in the public interest) and **Article 9(2)(b) — employment / social security / social protection law** for special-category data (health). Consent (Art 6(1)(a)) is **not** the primary basis because the data subject is a minor in care who cannot freely withhold consent without risking their placement.

| Category | Detail |
|----------|--------|
| **Applicable data** | All personally identifiable data of children, foster parents, and caseworkers who are EU residents. Special-category data includes `medical_events`, therapy notes, and any payload containing health, biometric, or behavioural data. |
| **Required technical controls** | • **Data classification** — every column tagged with sensitivity level in `information_schema.column_metadata` (we extend the `child_life_events` JSONB schema with a `_gdpr_category` key: `health`, `education`, `demographic`, `behavioural`, `caseworker`)<br>• **Right of access (Art 15)** — `GET /api/privacy/export/{child_id}` returns all data Artifex holds on that child as a structured JSON file within 30 days. The endpoint queries `children`, `placements`, `child_life_events`, `medical_events`, `crisis_predictions`, `ml_decision_audit` (filtered by child_id), `child_twin_states`<br>• **Right to erasure (Art 17)** — `POST /api/privacy/erase/{child_id}` does NOT hard-delete. It sets a `_gdpr_erasure_timestamp` annotation on every row and replaces PII columns with `[REDACTED PURSUANT TO GDPR ART 17]`. The ML audit trail is preserved (hash chain integrity) but `child_demographics` and `input_features` are nulled.  Reason: the data is still needed for the agency's legal obligations (mandated reporting, placement history audits). The child's data is *locked* but not *destroyed*.<br>• **Right to restrict (Art 18)** — a `data_subject_restricted` flag on `children` prevents any ML inference (crisis prediction, twin simulation, drift scoring) from running against that child. The `crisis_predictor` and `twin.simulate` routes check this flag before loading features.<br>• **Cross-border transfer (Art 44–49)** — if Artifex operates an EU instance or an EU agency sends data to the US data centre: **Standard Contractual Clauses (SCCs)** + Transfer Impact Assessment (TIA) executed with each EU customer. The `geo_context` field on each placement row records whether SCCs apply.<br>• **Pseudonymisation** — child_id replaced with a hash (`SHA-256(salt + child_id)`) in all ML training datasets and fairness monitoring exports. Raw child_id only accessible via a `child_lookup` table stored on a separate encryption key. |
| **Required policy controls** | • **DPO appointment** — documented Article 37 designation<br>• **Data Protection Impact Assessment (DPIA)** — completed before the twin simulation and fairness monitoring features were deployed (Art 35)<br>• **Records of processing** — maintained per Art 30; the `information_schema.column_metadata` extension auto-generates the data inventory section<br>• **Erasure procedure** — caseworker cannot approve an erasure request alone; a supervisor + DPO must co-sign because the child's safety may depend on the records. The `_gdpr_erasure_timestamp` has a 30-day cooling-off period before it takes effect.<br>• **International transfer register** — list of all customers using SCCs, transfer date, data categories transferred, TIA expiry |
| **Audit evidence** | • DPIA document (signed, versioned)<br>• SCCs executed for each EU customer (with signed counterparty)<br>• Erasure request log: child_id, request_date, cooling_off_end, erasure_executed_by, supervisor_id<br>• Article 30 record of processing activities (auto-generated from schema metadata)<br>• TIA renewal tracker (annual) |

### Right to Erasure — Worked Example

A 16-year-old in care requests erasure of all their data. The caseworker cannot approve — they escalate to supervisor + DPO.

```
1. Supervisor reviews: are records still needed for
   a) the child's own safety (mandated reporting)?
   b) a pending court case?
   c) sibling reunification planning?
2. If YES to any → data is RESTRICTED (Art 18) but not erased.
   The child is notified in plain language:
   "We cannot delete these records right now because [reason].
    We have locked them so no one can use them for new decisions."
3. If NO to all → erasure proceeds after 30-day cooling-off:
   - PII columns set to [REDACTED]
   - ML features nulled
   - Row-level `gdpr_erasure_timestamp` set
   - Audit hash chain still intact (no row is deleted)
```

---

## 3. FERPA (US — Family Educational Rights and Privacy Act)

### When FERPA Attaches

Artifex does not directly receive data from schools. Instead, caseworkers manually enter school enrolment data (school name, grade, attendance, IEP status) or a data-sharing agreement exists between the child welfare agency and the school district. If Artifex *receives* education records directly from a school under a written agreement, Artifex is a **school official** with a **legitimate educational interest** and must comply with FERPA's redisclosure restrictions.

| Category | Detail |
|----------|--------|
| **Applicable data** | `school_enrollments` (school_name, grade, attendance_rate_pct, iep_active, days_out_of_school), `children.school` (current school), child_life_events with `event_type = school_change` payload |
| **Required technical controls** | • **Redisclosure block** — the `GET /api/timeline/{child_id}` endpoint strips `school_enrollments` data from the response when the caller's role is NOT `caseworker` or `supervisor` and the org has not signed a data-sharing agreement. A `school_data_share_agreement_id` column on `children` controls this.<br>• **Audit trail** — every access to an education-record-containing payload is flagged with `ferpa_access = TRUE` in `audit_logs`<br>• **Directory information opt-out** — if a parent/guardian has opted out of directory information disclosure (§99.37), Artifex suppresses the child's school name in all UI and export views. A `ferpa_directory_opt_out` boolean column on `children` enables this. |
| **Required policy controls** | • **Data-sharing agreement** template for schools — defines that Artifex is a school official with a legitimate educational interest, lists the specific data fields, and specifies the redisclosure prohibition<br>• **Annual notification** — parent/guardian must be notified annually of their FERPA rights (Artifex provides a templated letter that agencies mail out)<br>• **Redisclosure log** — any onward transfer of education records (e.g., to a new school upon placement change) must be logged with recipient name, date, and purpose |
| **Audit evidence** | • School data-sharing agreements (indexed by `school_data_share_agreement_id`)<br>• Directory information opt-out records (`children.ferpa_directory_opt_out`)<br>• Redisclosure log (table: `ferpa_redisclosure_log` with columns: child_id, from_org, to_org, date, purpose, caseworker_id)<br>• Access logs with `ferpa_access = TRUE` (quarterly review by privacy officer) |

---

## 4. CCPA (California — California Consumer Privacy Act)

### Who It Covers

CCPA applies to Artifex if a California agency uses Artifex and Artifex meets one of:
- Annual gross revenue >$25M (Artifex likely does not yet)
- Buys/receives/sells personal information of ≥100,000 California residents
- Derives ≥50 % of revenue from selling personal information

Artifex does **not** sell personal information. However, many California counties using Artifex will have ≥100,000 children's records in aggregate, and Artifex "shares" personal information for cross-context behavioural advertising (which we do not do). So CCPA compliance is driven by **risk posture**, not a strict revenue threshold — California agencies will require it in procurement.

| Category | Detail |
|----------|--------|
| **Applicable data** | All personal information of California residents stored in Artifex, but especially `race`, `zip_code`, `fpl_percent` (added in migration 0004), special_needs, school, and any ML-derived scores. |
| **Required technical controls** | • **Right to know (CCPA §1798.110)** — same `GET /api/privacy/export/{child_id}` endpoint used for GDPR, but response must categorise data into the 11 CCPA categories (identifiers, protected class, commercial, biometric, internet activity, geolocation, sensory, employment, education, profile inferences). We map columns: `children.race` → "protected class", `children.fpl_percent` → "financial information", `zip_code` → "geolocation", crisis_predictions → "inferences".<br>• **Right to delete (CCPA §1798.105)** — parallel to GDPR erasure but with a shorter timeline (45 days, extendable by 45). The same `_gdpr_erasure_timestamp` mechanism is reused — CCPA does not require stricter deletion than GDPR.<br>• **Right to opt-out of sale (CCPA §1798.120)** — Artifex does not sell data. A `DO_NOT_SELL` page at `/privacy/do-not-sell` confirms this in plain language. The `sale_opt_out` flag exists on the user profile but defaults to `TRUE` (data not sold).<br>• **Service provider restrictions** (§1798.140(ag)) — Artifex contracts prohibit sub-processors from using the data for their own purposes. Each subcontractor (hosting provider, observability tool, ML inference provider) is listed in the CCPA disclosure with purpose and data categories.<br>• **Sensitive data minimization** — `race`, `fpl_percent`, and special_needs are excluded from the default API response; callers must affirm a purpose code ("fairness monitoring", "compliance reporting") via an `X-Purpose` header to receive these fields. |
| **Required policy controls** | • **Privacy notice** — updated to include CCPA-specific disclosures: categories of PI collected, business purpose, categories of third parties, right to know/delete/opt-out, non-discrimination<br>• **Sub-processor register** — list of all vendors with access to California PI, contract clause requiring the same level of privacy protection<br>• **Metrics reporting** (§1798.185(b)) — annual report of requests received, complied with in full, complied with in part, denied, and average days to respond |
| **Audit evidence** | • CCPA compliance statement (annual re-certification)<br>• Deletion request log (shared with GDPR, but CCPA-specific fields: county_of_residence, request_channel, response_deadline)<br>• Sub-processor register with CCPA exhibit links<br>• Purpose-code access logs (query: `SELECT * FROM audit_logs WHERE purpose_header IS NOT NULL AND timestamp > NOW() - INTERVAL '1 year'`) |

---

## 5. NY Child Welfare Data Privacy (New York)

### Why NY Is Complex

New York imposes specific child welfare data protections beyond HIPAA and FERPA through:
- **NY Social Services Law (SSL) §372** — confidentiality of child welfare records; disclosure only to persons with a "valid purpose" directly connected with the administration of the child welfare system
- **NY Family Court Act (FCA) §166** — court records in child welfare proceedings are sealed; unauthorised disclosure is a class A misdemeanour
- **NY OCFS 18 NYCRR Part 428** — state regulations specific to authorised access, redisclosure limitations, and record retention for child welfare data
- **NY SHIELD Act (S5682B)** — not SHEA but the Stop Hacks and Improve Electronic Data Security Act — broad data security requirements that apply to any entity holding private data of New York residents

| Category | Detail |
|----------|--------|
| **Applicable data** | **SSL §372** — any record or report concerning a child in the child welfare system (referrals, investigations, placement history, service plans, court orders). This is broader than HIPAA's definition of PHI. **SHIELD Act** — any private data (name + any of: SSN, driver's licence, biometric, email + password, health data, financial account). |
| **Required technical controls** | • **SSL §372 valid-purpose check** — every API response that includes child welfare records must include a `purpose_code` header set by the requesting client. The audit log records this purpose. Endpoints that return records without a valid purpose return HTTP 403.<br>• **FCA §166 seal enforcement** — the `seal_level` column on `child_life_events` has a mandatory minimum of `partial` for any event sourced from a Family Court proceeding. The `superseded_by` chain (append-only) means sealed records are never truly deleted — they are hidden from non-court-authorized users. The `GET /api/timeline/{child_id}` endpoint requires a `?court_order=` parameter to unseal court-sourced events.<br>• **18 NYCRR 428 redisclosure lock** — a `redisclosure_block` flag on `children` prevents any NATS event or WebSocket broadcast from including that child's data. When set, the system logs a warning and drops the payload from the message bus.<br>• **SHIELD Act data security (§899-bb)** — requires "reasonable safeguards" including: risk assessment, workforce training, incident response plan, and **notification within 30 days** for any breach of private data (stricter than HIPAA's 60 days for >500). The existing breach-detection alert (5+ children viewed in 10 min) is configured to email the privacy officer within 24 hours under SHIELD Act requirements.<br>• **Retention schedule (18 NYCRR 428.10)** — child welfare records retained until 6 years after case closure, or 10 years if the child was placed in foster care (whichever is later). The `archival_policy` column on `children` tracks the retention expiration date. Automated archival moves the row to a `children_archived` table at retention expiry. |
| **Required policy controls** | • **Valid-purpose catalogue** — documented list of acceptable purpose codes (e.g., `placement_matching`, `court_hearing`, `healthcare_coordination`, `fairness_monitoring`, `research_irb_approved`) with the minimum data fields each purpose authorises<br>• **Seal-level governance** — policy defining which event types map to which seal levels; only a supervisor or judge may set `seal_level = full`; all changes logged to `child_life_events.superseded_by`<br>• **SHIELD Act incident response plan** — documented plan with tabletop exercise schedule (annual), notification template (30-day), and NY State Attorney General contact<br>• **Redisclosure training** — annual workforce training on NY SSL §372, FCA §166, and 18 NYCRR Part 428, with attestation recorded in the caseworker's profile |
| **Audit evidence** | • Purpose-code audit log (year-over-year trend)<br>• Sealed record access log (court-order token validation, timestamps, requesting user)<br>• SHIELD Act risk assessment (updated annually)<br>• Retention-expiration batch job logs (monthly: "X records archived, Y records destroyed")<br>• Redisclosure-block incidents log ("NATs payload suppressed for child_id ZZZ at timestamp T — purpose was `placement_matching` but redisclosure_block was set")<br>• Training attestation records per caseworker (annual) |

---

## Cross-Cutting Control Mapping

| Technical control | HIPAA | GDPR | FERPA | CCPA | NY |
|-------------------|-------|------|-------|------|----|
| Encryption at rest (AES-256) | ✅ §164.312(a)(2)(iv) | ✅ Art 32 | — | — | ✅ SHIELD Act |
| Encryption in transit (TLS 1.3) | ✅ §164.312(e)(1) | ✅ Art 32 | — | — | ✅ SHIELD Act |
| Access logging with user_id | ✅ §164.312(b) | ✅ Art 5(2) | ✅ §99.31 | ✅ §1798.130 | ✅ SSL §372 |
| Role-based access control | ✅ §164.312(a)(1) | ✅ Art 25 | ✅ §99.31 | ✅ §1798.135 | ✅ 18 NYCRR 428 |
| Breach notification (automated) | ✅ §164.404 | ✅ Art 33 | — | ✅ §1798.150 | ✅ SHIELD Act 30-d |
| Data portability export | — | ✅ Art 15 | — | ✅ §1798.110 | — |
| Erasure / redaction flow | — | ✅ Art 17 | — | ✅ §1798.105 | ✅ SSL §372 retention |
| Purpose-binding header | — | ✅ Art 5(1)(b) | ✅ §99.31 | ✅ §1798.100 | ✅ SSL §372 |
| Redisclosure control | ✅ BAA | — | ✅ §99.33 | ✅ §1798.140(ag) | ✅ 18 NYCRR 428 |
| Retention schedule enforcement | ✅ §164.316(b)(2) | ✅ Art 5(1)(e) | — | ✅ §1798.130 | ✅ 18 NYCRR 428.10 |
| Data-sharing agreement (SCC/BAA) | ✅ BAA | ✅ SCCs | ✅ Agreement | ✅ Service provider | ✅ SSL §372 |
| Hash-chain audit integrity | ✅ §164.312(c)(2) | ✅ Art 5(2) | — | — | — |

## Implementation Priority

| Regulation | Artifex feature / migration | Deadline (if operating today) |
|------------|----------------------------|-------------------------------|
| **HIPAA** | BAA signing, audit-log PHI flag, `medical_events` column encryption | Pre-production |
| **GDPR** | `GET /api/privacy/export`, `POST /api/privacy/erase`, SCCs, DPO designation | Any EU customer |
| **FERPA** | School data-sharing agreement model, `ferpa_directory_opt_out`, `ferpa_redisclosure_log` table | Any use of school records |
| **CCPA** | Purpose-code header enforcement (`X-Purpose`), `sale_opt_out` flag, sub-processor register | California county customer |
| **NY** | `purpose_code` audit column, court-order token for `/api/timeline`, `redisclosure_block`, retention batch job, SHIELD Act incident response plan | New York county customer |
