# Child Digital Twin — Product Concept

> **Status:** Exploratory · **Owner:** Research Science  
> **Date:** 2026-06-01  
> **Applies to:** Artifex Predictive Crisis Engine

---

## 1. What Is a Child Digital Twin?

A **Child Digital Twin** is a continuously-updated probabilistic model of a child's welfare trajectory while in foster care. It is *not* a real-time rendering or a chatbot — it is a structured, queryable outcome simulator.

For each child in placement, the twin encodes:

- The child's static attributes (age, gender, special needs, intake reason, emergency level)
- The child's dynamic state (behavioural drift signals, school engagement, medication compliance, caseworker sentiment trends)
- The placement context (foster family attributes, sibling separation, caseworker assignment, visit frequency)
- A causal model of how these factors interact to produce outcomes (stable placement, disruption, reunification, runaway)

The twin is updated whenever new data arrives (a check-in is submitted, a behavioural drift snapshot is ingested, a school attendance record is posted). Each update refines the probability distributions that power simulation.

At any point, a caseworker can ask: *"What is likely to happen to this child over the next 4 weeks?"* — and the twin answers with a distribution over outcomes, not a single number.

---

## 2. Data Inputs Composing the Twin

The twin draws from seven data domains, all already present in the Artifex schema or its near-term extensions:

| Domain | Source tables | Refresh cadence | Twin role |
|---|---|---|---|
| **Placement history** | `placements`, `active_placements`, `placement_history` | Continuous (event-driven) | Defines the current placement context and past disruption patterns |
| **School records** | `children.school`, `children.school_changes`, attendance fields in `behavioural_drift_signals` | Weekly (via drift pipeline) | School stability is one of the strongest predictors of placement success |
| **Behavioural signals** | `behavioural_drift_signals.signals_json` (attendance, incidents, medication, communication, caseworker sentiment) | Weekly (drift snapshot) | The primary leading indicator of impending disruption |
| **Caseworker notes** | `check_ins.notes`, keyword flags in `behavioural_drift_signals.caseworker_visits.entries[].keyword_flags` | Per-visit (NATS event) | Sentiment and flag trends feed the stochastic model |
| **Family contact frequency** | `check_ins`, caseworker visit entries (derived) | Per-visit | Visit frequency decay is a proxy for engagement risk |
| **Health records** | `children.medical_needs`, medication compliance fields in drift signals | Weekly | Medication non-compliance is an early-warning signal |
| **Demographics & intake** | `children` (age, race, gender, special_needs, emergency_level, intake_reason) | Static (at intake) | Used for similarity matching and historical baseline computation |

### Twin Composition Pipeline

```
Raw events (NATS) → Signal pipeline → behavioural_drift_signals
                                      ↙
Foster placement events → Placement History → Twin State Store (JSONB)
                                                ↕
                               Counterfactual Simulator (XGBoost quantile
                               regression forests + causal graph)
```

The **Twin State Store** is a new `child_twin_states` table:

```sql
CREATE TABLE child_twin_states (
    child_id           TEXT     PRIMARY KEY REFERENCES children(child_id),
    placement_id       TEXT     REFERENCES placements(workflow_id),
    as_of              TIMESTAMP NOT NULL DEFAULT NOW(),

    -- Current state vector (derived features used by the simulator)
    current_features   JSONB    NOT NULL,

    -- Cached outcome distribution
    outcome_probs      JSONB,   -- {stable, disrupted, reunified, runaway}

    -- Top-K counterfactual recommendations
    pending_simulations JSONB,  -- [sim_id, feature_delta, projected_outcome, ci]

    -- Metadata
    version            INT      NOT NULL DEFAULT 1,
    updated_at         TIMESTAMP NOT NULL DEFAULT NOW(),
    stale_at           TIMESTAMP NOT NULL DEFAULT NOW() + INTERVAL '7 days'
);
```

The twin is **stale** after 7 days without new data — the system flags it for the caseworker and schedules a re-simulation.

---

## 3. What "Simulation" Means

Simulation is **not** a physical or visual representation. There is no avatar, no dashboard talking head, no chat interface pretending to be the child.

A simulation is a structured query against the twin that returns a **probabilistic outcome distribution**.

### Mechanics

1. **Current state vector** — The twin's `current_features` JSONB captures ~55 features (same as the crisis predictor pipeline, plus family contact frequency, sibling visit cadence, and caseworker rotation count).

2. **Intervention specification** — The caseworker (or automated workflow) specifies a delta:
   ```
   {
     "change_school": true,
     "new_placement_id": "family-0452",
     "visitation_frequency": "weekly",
     "therapy_intensity": "increased"
   }
   ```

3. **Modified state vector** — The simulator applies the intervention deltas to the current state vector, producing counterfactual states. For each counterfactual, it runs a **stochastic forward pass** through an ensemble of 100 XGBoost quantile regression trees (already used in the crisis predictor) with injected noise drawn from the residual distribution of the training data.

4. **Outcome distribution** — Each pass produces a sampled outcome over a configurable horizon (14, 21, or 28 days). The ensemble yields:
   ```
   {
     "no_intervention": {
       "disruption_prob": 0.72,
       "ci_95": [0.61, 0.83],
       "most_likely_outcome": "disrupted"
     },
     "with_intervention": {
       "disruption_prob": 0.34,
       "ci_95": [0.22, 0.47],
       "most_likely_outcome": "stable"
     },
     "effect_size": -0.38,
     "probability_of_benefit": 0.89,
     "number_needed_to_treat": 3
   }
   ```

5. **Confidence calibration** — The quantile forests natively produce prediction intervals. Additional conformal prediction calibration (split-conformal on a held-out set of 500 historical placements) ensures coverage validity across demographic subgroups.

### What simulation is NOT

| Not this | This |
|---|---|
| A prediction that "Child X will disrupt on date Y" | A distribution: "Under current trajectory, 72% of similar placements disrupt within 21 days" |
| A recommendation that replaces caseworker judgment | A decision-support tool that ranks intervention options by effect size |
| A static score | A living model that updates with every new behavioural drift signal |
| A guarantee | A calibrated probability with confidence intervals |

---

## 4. Key Counterfactual Questions

Caseworkers face high-dimensional decisions with correlated interventions. The twin is designed to answer compound counterfactuals that are difficult to evaluate intuitively.

### Primary query types

| Question type | Example | Decision relevance |
|---|---|---|
| **Single-variable** | "What happens if we increase caseworker visits from biweekly to weekly?" | Low-cost intervention triage: small changes with potentially large effects |
| **Compound** | "What if we change school AND placement simultaneously?" | High-stakes: removing a child from their school and family simultaneously may compound trauma — or be the right call if both are failing |
| **Sequencing** | "Should we increase therapy first or change placement first?" | Timing matters — the order of interventions changes outcomes |
| **Threshold** | "At what point does visitation frequency become ineffective?" | Resource allocation: diminishing returns on caseworker time |
| **Adversarial** | "What would need to happen for this child to disrupt despite all interventions?" | Risk discovery: identifying edge cases where the system cannot prevent disruption |

### Query interface

```python
# SDK-style query (authored by caseworker through UI or by automated workflow)
from artifex.twin import ChildTwin

twin = ChildTwin(child_id="CH-A0427")

result = await twin.counterfactual(
    horizon_days=28,
    intervention={
        "change_school": True,
        "new_placement_id": "family-0452",
        "visitation_frequency": "weekly",
    },
    baseline="no_intervention",
    n_samples=1000,
)

print(result.effect_size)           # -0.38
print(result.probability_of_benefit) # 0.89
print(result.ci_95)                 # (0.22, 0.47)
```

### Output visualisation (UI mockup)

```
┌────────────────────────────────────────────────────────────────────────────┐
│ ╳ Counterfactual Simulator — CH-A0427                    Age 9 · 14 wks  │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Current trajectory (no change)                   Sim: change school + placement │
│  ┌─────────────────────────────────────┐         ┌──────────────────────────┐
│  │ Disruption risk: 72% [61–83]       │         │ Disruption risk: 34% [22–47] │
│  │ Most likely: disrupted in 18 days   │         │ Most likely: stable         │
│  │                                     │         │                            │
│  │ RISK  ████████████████████████████░ │         │ RISK  ████████░░░░░░░░░░░░ │
│  └─────────────────────────────────────┘         └──────────────────────────┘
│                                                                             │
│  Effect size: −38pp │ Probability of benefit: 89% │ NNT: 3                  │
│                                                                             │
│  Top drivers of improvement:                                                │
│    • School change: −18pp — current school has 42% absentee rate           │
│    • New placement: −14pp — family-0452 has sibling-group capacity          │
│    • Interaction:   −6pp  — combined effect exceeds sum of individuals     │
│                                                                             │
│  [Schedule combined intervention]  [Run another simulation]  [Export]      │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Ethical Guardrails

The Child Digital Twin poses risks common to predictive systems in child welfare, plus new risks specific to counterfactual simulation. The following guardrails are mandatory.

### 5.1 Decision Authority

**The twin never makes a decision.** It answers questions; it does not recommend actions. The simulation output is a probability distribution, not an instruction.

- No "recommend" button anywhere in the simulation UI — only "Schedule intervention" (which routes to a caseworker's task list) and "Export" (for documentation).
- All counterfactual outputs are displayed with confidence intervals. A point estimate without a CI is never shown.
- The twin is blocked from answering comparisons that omit the "do nothing" baseline. Every simulation must show current trajectory vs. counterfactual.

### 5.2 Stochastic Fallibility

Every simulation output must include a calibrated error disclosure:

```
⚠️ This simulation is based on patterns from 1,240 historical placements.
Outcomes for individual children vary. The confidence interval captures
this uncertainty. Do not use this alone to make placement decisions.
```

- Conformal prediction coverage is validated quarterly across all demographic subgroups. If coverage dips below 90% for any group (race, SES, gender, age), the twin is taken offline for that group until recalibrated.
- The ensemble of 100 trees is audited monthly for distribution shift. If the average prediction interval width increases by more than 20% in a week, the twin for that child is marked as "stale — re-simulation required."

### 5.3 Prohibition on Risk-Stratified Resource Withholding

The twin must never be used to **reduce** services to a child based on a low predicted risk.

- Use case forbidden: "Child X has only 12% disruption risk — we can reduce their caseworker visits to monthly."
- If a simulation shows low risk, the output must still include: *"Low predicted risk does not guarantee a stable outcome. Continue standard monitoring per agency protocol."*
- The twin's outputs may only be used to **add or reallocate** resources, never to withdraw them.

### 5.4 Human-in-the-Loop for Compound Interventions

Any simulation involving two or more simultaneous changes (e.g., change school AND change placement) requires:

1. A supervisor review of the combined plan before it can be scheduled
2. An explicit justification field: "Why are both changes needed at the same time?"
3. A fallback simulation comparing the compound intervention to the best single-change intervention

This prevents the system from recommending high-risk compound changes without human scrutiny, especially for children with high ACE (Adverse Childhood Experiences) scores where compounding interventions may increase trauma.

### 5.5 Bias Monitoring

Every counterfactual simulation is logged in the `ml_decision_audit` table with `decision_type='counterfactual_simulation'` and the full input/output captured in `input_features` / `output_details`.

Weekly fairness audits (via `WeeklyFairnessWorkflow`) compute:

- **Simulation access parity** — Are caseworkers requesting simulations at equal rates across demographic groups? Unequal request rates could mean the tool is being used to scrutinise some groups more than others.
- **Intervention recommendation parity** — Does the twin show similar effect sizes for similar children across groups? If not, the causal model may encode bias.
- **False reassurance rate** — How often does the twin predict low risk for a child who later disrupts? Tracked by demographic group. If FNR differs across groups, the conformal calibration is adjusted.

Any of the three metrics entering REVIEW status blocks the twin from producing new simulations until the issue is resolved.

### 5.6 Audit Trail and Explainability

Every simulation is a permanent, tamper-evident record:

```
GET /api/ml-audit/decisions?decision_type=counterfactual_simulation&child_id=CH-A0427

Returns:
  {
    "id": 39100,
    "child_id": "CH-A0427",
    "decision_type": "counterfactual_simulation",
    "input_features": {
      "age": 9,
      "weeks_in_placement": 14,
      "school_attendance_rate": 0.70,
      "current_risk_score": 72,
      "proposed_placement_change": "family-0452",
      "proposed_school_change": true,
      "proposed_visitation": "weekly"
    },
    "output_details": {
      "baseline_disruption_prob": 0.72,
      "counterfactual_disruption_prob": 0.34,
      "effect_size": -0.38,
      "probability_of_benefit": 0.89,
      "n_samples": 1000,
      "model_version": "twin-v1-2026-06",
      "requested_by": "caseworker-043",
      "supervisor_approved": true
    },
    "hash": "ff1a2b3c...",
    "decided_at": "2026-06-01T14:30:00Z"
  }
```

### 5.7 Opt-Out

Agency policy can disable the twin for:

- **Individual children** (at a caseworker's request)
- **Demographic groups** (if fairness metrics trigger a BLOCK)
- **Decision types** (e.g., prohibit school-change simulations)
- **The entire agency** (kill switch via environment variable `TWIN_ENABLED=false`)

When disabled, the twin returns: *"Counterfactual simulation is not available for this child. Contact your agency administrator for details."*

---

## 6. Implementation Phases

| Phase | Scope | Timeline | Dependencies |
|---|---|---|---|
| **Phase 1** | `child_twin_states` table + state vector pipeline (aggregate existing features into JSONB) | 1 sprint | Migration 0005 |
| **Phase 2** | Single-variable counterfactual engine (using existing XGBoost quantile forests) | 2 sprints | Crisis predictor v2 |
| **Phase 3** | Compound + sequencing counterfactuals with interaction-term detection | 2 sprints | Phase 2 |
| **Phase 4** | UI for caseworkers (simulation explorer, intervention scheduler) | 2 sprints | Phase 3 |
| **Phase 5** | Bias monitoring dashboard + supervisory review workflow | 1 sprint | FairnessAuditDashboard |
| **Phase 6** | Conformal prediction calibration quarterly validation pipeline | Ongoing | Phase 2 |

---

*This concept is exploratory. No code has been written for the Child Digital Twin. The existing crisis predictor, behavioural drift pipeline, and ml_decision_audit table provide the data foundation, but the twin's causal model, counterfactual engine, and UI are new components.*
