# Child Digital Twin — Simulation Engine Design

> **Status:** Technical design · **Owner:** Research Science  
> **Date:** 2026-06-01  
> **Applies to:** Artifex Predictive Crisis Engine

---

## 1. Causal Inference Strategy

### 1.1 Why Not a Full SCM?

A full Structural Causal Model (graph + structural equations + do-calculus) would be the gold standard for reasoning about interventions. In child welfare data it is the wrong choice for three reasons:

| Problem | Consequence |
|---|---|
| **Unknown graph structure** — The causal relationships between school attendance, caseworker visits, medication compliance, and placement stability are not well-characterised in the literature. Any DAG we specify would be highly contested and almost certainly misspecified. | Misspecified DAGs produce arbitrarily wrong estimates that cannot be validated without an oracle. |
| **Latent confounders** — The primary confounders in child welfare (household trauma history, caregiver mental health, community violence exposure) are not captured in structured data. No DAG can adjust for unmeasured variables. | Sensitivity analysis becomes the dominant concern, not graph structure. |
| **Sparse disruption events** — Only ~5–8% of placements disrupt. Structural equation models fitted to rare events with 55+ covariates and latent variables exhibit extreme finite-sample bias. | A parametric SCM would produce estimates with variance so high they are unusable for individual-level counterfactuals. |

**Decision:** We do not build a full SCM. Instead, we adopt a **two-layer identification strategy** that combines Double/Debiased Machine Learning (DML) for average and conditional average treatment effects with a lightweight causal graph that is used *only* for confounder selection, not for identification.

### 1.2 Primary Estimator: Causal Forest (EconML)

**`CausalForest`** from the EconML library is the primary estimator. It is a random forest that grows splits to maximise heterogeneity in treatment effect (τ(X)), not heterogeneity in outcomes (Y).

Why CausalForest for this setting:

| Property | Relevance |
|---|---|
| **Handles high-dimensional confounding** — With 55+ features and ~2000 historical placements, we are in the p ≪ n regime but with weak signals. CausalForest's honest splitting and regularisation prevent overfitting. | We cannot afford to drop features — many weak signals together may identify effect heterogeneity. |
| **Natively estimates CATE** — τ(x) = E[Y₁ − Y₀ | X = x] without manual interaction modelling. | Caseworkers need *individualised* answers, not population averages. |
| **Asymptotically normal** — Provides confidence intervals via the infinitesimal jackknife. | Every counterfactual output requires a CI. |
| **No DAG required** — Relies on unconfoundedness + overlap, which we defend via domain knowledge + sensitivity analysis. | Avoids the DAG specification problem. |
| **Multi-valued treatment support** — CausalForest can handle categorical treatments with >2 levels via the `CausalForestDML` wrapper or by fitting separate forests. | Interventions are multi-valued (different schools, different placement types, different frequencies). |

### 1.3 Defending Unconfoundedness

CausalForest assumes **unconfoundedness**: Y(0), Y(1) ⟂ T | X. In observational child welfare data this is never literally true. We defend it through three mechanisms:

**1. Rich feature set** — The 55-feature vector captures:
- All behavioural drift signals (attendance, incidents, medication, communication, sentiment)
- Placement characteristics (family experience, sibling capacity, special-needs training)
- Caseworker assignment (individual caseworker fixed effects via embedding)
- Time in placement and placement history features

This is not exhaustive, but it captures the *observable* assignment mechanism. Caseworkers explicitly document *why* they change a school or a placement — these reasons appear in `check_ins.notes` and `caseworker_visits.keyword_flags`.

**2. Negative control outcomes** — For each intervention type, we define a negative control outcome that should NOT be affected by the intervention:
- *Example:* Changing schools should not affect medication compliance rates within the first week. If our CausalForest estimate shows an effect, unconfoundedness is violated.
- Negative control tests are automated in the weekly fairness workflow:
  ```python
  def test_unconfoundedness(intervention_type, negative_control_outcome):
      est = CausalForest(...)
      effect = est.estimate(intervention_type, negative_control_outcome)
      assert effect.confidence_interval().contains(0), \
          f"Unconfoundedness likely violated for {intervention_type}"
  ```

**3. Sensitivity analysis via `causalml`** — The `causalml` library provides `Sensitivity` class that quantifies how strong an unmeasured confounder would need to be to overturn the conclusion:
```python
from causalml.sensitivity import Sensitivity
sensitivity = Sensitivity()
# "An unmeasured confounder would need to shift the treatment effect by
#  0.38 standard deviations to nullify the estimated benefit."
```

If the required confounder strength exceeds any observed covariate's effect, the estimate is treated as robust.

### 1.4 Handling Compound Interventions

Compound interventions (e.g., change school AND placement simultaneously) are the hardest case. Three strategies are used, ranked by preference:

**Strategy A — Interaction Causal Forest (preferred)**

Fit a CausalForest with multi-valued treatment that includes an interaction term:
```python
from econml.grf import CausalForest

# Treatment is a tuple: (school_change, placement_change, visitation_change)
# encoded as a single categorical variable with 2^K levels
T = encode_treatment(school_change, placement_change, visitation_change)

cf = CausalForest(n_estimators=200, min_samples_leaf=10, honest=True)
cf.fit(Y, T, X=X, W=confounders)

# CATE for the compound intervention vs. no intervention
cate_compound = cf.effect(X_child, T0="none", T1="school+placement")

# Decompose into main effects + interaction
cate_school = cf.effect(X_child, T0="none", T1="school_only")
cate_placement = cf.effect(X_child, T0="none", T1="placement_only")
interaction = cate_compound - cate_school - cate_placement
```

This is preferred because it directly estimates the joint effect and the interaction term. However, the number of treatment cells grows exponentially with the number of simultaneous interventions, so we limit compound queries to at most 2 simultaneous changes.

**Strategy B — Double ML with product terms (fallback)**

When the compound treatment has too few examples (fewer than 30 instances in the training data), fall back to a Double ML estimator with a product interaction term:
```python
from econml.dml import LinearDML

est = LinearDML(
    model_y=GradientBoostingRegressor(),
    model_t=GradientBoostingClassifier(),
    discrete_treatment=True,
    treatment_featurizer=PolynomialFeatures(degree=2, interaction_only=True),
)
est.fit(Y, T, X=X, W=confounders)
```

The `PolynomialFeatures(interaction_only=True)` creates the school × placement interaction term automatically. The DML framework debiases the estimate even with high-dimensional product terms.

**Strategy C — Sensitivity bounds (when both fail)**

If neither A nor B produces stable estimates (variance > 0.5 × mean effect), the twin returns a **bounds-only** response:
```
⚠️ Insufficient historical data to estimate the combined effect.
  Single-intervention effects:
    Change school alone:   −18pp [−28, −8]
    Change placement alone: −14pp [−22, −6]
  Estimated combined range: −18pp to −38pp
  (Lower bound assumes additive effects; upper bound assumes positive interaction.)
```

---

## 2. Confounder Handling

### 2.1 Confounder Selection Graph

Rather than a full DAG, we use a **confounder selection diagram** — a minimal directed graph that identifies which variables must be adjusted for. Variables not in the graph are either mediators (which we explicitly do NOT adjust for) or irrelevant.

```
                    ┌──────────────────┐
                    │ Intake attributes│───→ Age, gender, special_needs,
                    │ (static)         │     emergency_level, intake_reason
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │ Placement context│───→ Family experience, sibling capacity,
                    │ (static/rarely   │     special_needs_trained, caseworker_id
                    │  changing)       │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │ Current signals   │───→ Attendance, incidents, medication,
                    │ (dynamic weekly)  │     sentiment, communication
                    └────────┬─────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
     ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
     │ School      │ │ Placement   │ │ Visitation  │
     │ change (T₁) │ │ change (T₂) │ │ change (T₃) │
     └──────┬──────┘ └──────┬──────┘ └──────┬──────┘
            │              │              │
            └──────┬───────┴───────┬──────┘
                   ▼               ▼
          ┌────────────────┐ ┌────────────────┐
          │ Placement      │ │ Behavioural    │
          │ stability (Y₁) │ │ trajectory (Y₂)│
          └────────────────┘ └────────────────┘
```

**Adjustment set** (variables that enter as W in CausalForest): `intake_attributes ∪ placement_context ∪ current_signals`.

**Mediators** (NOT adjusted for, to avoid over-control bias): `{intermediate behavioural signals between treatment and outcome}`.

If we adjusted for mediators, we would block the very causal path we are trying to estimate.

### 2.2 Handling Time-Varying Confounding

Interventions are not instantaneous — the confounder graph repeats at each time step. A change in caseworker visits in week 3 can be confounded by school attendance in week 2, which itself may have been affected by earlier caseworker visits.

For this we use **Doubly Robust (DR) estimation** across 7-day time windows with a modified g-computation:

```python
# For each 7-day window, estimate the treatment effect using DR,
# then average across windows with inverse-variance weighting.
from econml.dr import DRLearner

dr = DRLearner(
    model_propensity=GradientBoostingClassifier(),
    model_regression=GradientBoostingRegressor(),
    model_final=CausalForest(),
)
dr.fit(Y, T, X=X, W=time_varying_confounders)
```

The DR estimator is doubly robust: it is consistent if either the propensity model or the outcome regression is correctly specified. This provides protection against misspecification in the time-varying setting.

### 2.3 Sensitivity to Unobserved Confounding

We report a **Robustness Value** (RV) for every simulation:

```
RV = 0.38  — An unobserved confounder would need to explain 38% of the
             residual variance of both treatment and outcome to overturn
             the estimated effect.
```

Compared to observed covariates:

| Covariate | Covariance with T | Covariance with Y | Would overturn? |
|---|---|---|---|
| `baseline_incident_rate` | 0.12 | 0.18 | No (RV > both) |
| `caseworker_sentiment` | 0.08 | 0.22 | No |
| Any unobserved confounder | ? | ? | Only if strength ≥ 0.38 |

Implementation: `EconML` provides `CausalForest.refute()` with `bootstrap_refutation`, `placebo_treatment_refutation`, `random_common_cause_refutation`, `add_unobserved_common_cause` (from `causalml`).

```python
from econml.cate_interpreter import SingleTreeCateInterpreter

# Quantify sensitivity
refutation = cf.refute(
    method="add_unobserved_common_cause",
    confounder_strength=0.5,
    confounder_effect=0.5,
)
# Returns: estimated effect under additional unobserved confounder
# If the effect remains significant, the estimate is robust.
```

---

## 3. Output Format

### 3.1 Canonical Simulation Response

Every simulation returns a structured JSON response with three sections.

```python
@dataclass
class SimulationResult:
    # ── Metadata ──────────────────────────────────────────────────────
    child_id: str
    simulation_id: str
    generated_at: datetime
    model_version: str
    n_historical_placements: int  # training set size for reference

    # ── Baseline trajectory ───────────────────────────────────────────
    baseline: TrajectoryForecast
    #   .outcome_distribution: { "stable": float, "disrupted": float,
    #                            "reunified": float, "runaway": float }
    #     at days [30, 60, 90]
    #   .ci_95: { "stable": (float, float), "disrupted": (float, float), ... }
    #     per outcome per time point
    #   .dominant_outcome: str
    #   .uncertainty_score: float  # entropy of the distribution

    # ── Counterfactual trajectory ─────────────────────────────────────
    counterfactual: TrajectoryForecast
    #   Same structure as baseline

    # ── Effect summary ────────────────────────────────────────────────
    effect: EffectSummary
    #   .effect_size: float           # P(disrupt|baseline) − P(disrupt|CF)
    #   .probability_of_benefit: float  # fraction of samples where CF > baseline
    #   .number_needed_to_treat: float
    #   .ci_95: (float, float)
    #   .interaction_effect: float | None  # for compound interventions
    #   .robustness_value: float
    #   .sensitivity: SensitivityReport
    #       .confounder_strength_to_nullify: float
    #       .most_sensitive_feature: str
    #       .most_sensitive_feature_effect: float
```

### 3.2 Example Full Response

```json
{
  "child_id": "CH-A0427",
  "simulation_id": "sim_a1b2c3d4",
  "generated_at": "2026-06-01T14:30:00Z",
  "model_version": "twin-causal-forest-v1-2026-06",
  "n_historical_placements": 1842,

  "intervention": {
    "type": "compound",
    "components": [
      { "domain": "school", "action": "change", "value": "Lincoln Elementary → Washington Elementary" },
      { "domain": "placement", "action": "change", "value": "family-0123 (current) → family-0452 (proposed)" }
    ]
  },

  "baseline": {
    "outcome_distribution": {
      "30_days":  { "stable": 0.18, "disrupted": 0.72, "reunified": 0.06, "runaway": 0.04 },
      "60_days":  { "stable": 0.12, "disrupted": 0.78, "reunified": 0.07, "runaway": 0.03 },
      "90_days":  { "stable": 0.09, "disrupted": 0.81, "reunified": 0.08, "runaway": 0.02 }
    },
    "ci_95": {
      "30_days": {
        "stable":    [0.10, 0.28],
        "disrupted": [0.61, 0.83],
        "reunified": [0.02, 0.11],
        "runaway":   [0.01, 0.08]
      }
    },
    "dominant_outcome": "disrupted",
    "uncertainty_score": 0.42
  },

  "counterfactual": {
    "outcome_distribution": {
      "30_days":  { "stable": 0.54, "disrupted": 0.34, "reunified": 0.08, "runaway": 0.04 },
      "60_days":  { "stable": 0.48, "disrupted": 0.39, "reunified": 0.09, "runaway": 0.04 },
      "90_days":  { "stable": 0.42, "disrupted": 0.44, "reunified": 0.10, "runaway": 0.04 }
    },
    "ci_95": {
      "30_days": {
        "stable":    [0.40, 0.68],
        "disrupted": [0.22, 0.47],
        "reunified": [0.03, 0.14],
        "runaway":   [0.01, 0.08]
      }
    },
    "dominant_outcome": "stable",
    "uncertainty_score": 0.38
  },

  "effect": {
    "effect_size": -0.38,
    "probability_of_benefit": 0.89,
    "number_needed_to_treat": 3.0,
    "ci_95": [-0.52, -0.24],

    "decomposition": {
      "school_change_alone": -0.18,
      "placement_change_alone": -0.14,
      "interaction_effect": -0.06,
      "interaction_pct": 16
    },

    "robustness_value": 0.38,
    "sensitivity": {
      "confounder_strength_to_nullify": 0.38,
      "most_sensitive_feature": "baseline_incident_rate",
      "most_sensitive_feature_effect": 0.22,
      "placebo_test_passed": true,
      "negative_control_passed": true
    }
  }
}
```

### 3.3 Sensitivity Analysis Breakdown

The `sensitivity` block is generated from four automated tests:

```python
def sensitivity_report(cf: CausalForest, X_child: np.ndarray) -> dict:
    # 1. Confounder strength required to nullify
    from econml.sensitivity import SparseLinearSensitivity
    sens = SparseLinearSensitivity()
    strength_to_nullify = sens.confounder_strength_to_nullify(
        cf, X_child, alpha=0.05
    )

    # 2. Most sensitive feature
    #    Leave-one-covariate-out to measure influence on CATE
    base_cate = cf.effect(X_child)
    influences = {}
    for i, name in enumerate(feature_names):
        X_loo = np.delete(X_child, i, axis=1)
        loo_cf = CausalForest().fit(Y_loo, T_loo, X=X_loo, W=W_loo)
        influences[name] = abs(loo_cf.effect(X_loo) - base_cate)
    most_sensitive = max(influences, key=influences.get)

    # 3. Placebo test — randomise treatment, verify no effect
    from econml.refutation import placebo_treatment_refutation
    placebo_passed = placebo_treatment_refutation(cf, X, Y, T, W, random_state=42)

    # 4. Negative control outcome
    negative_control_passed = test_unconfoundedness(treatment_type, negative_control)

    return {
        "confounder_strength_to_nullify": strength_to_nullify,
        "most_sensitive_feature": most_sensitive,
        "most_sensitive_feature_effect": influences[most_sensitive],
        "placebo_test_passed": placebo_passed,
        "negative_control_passed": negative_control_passed,
    }
```

---

## 4. Model Validation

### 4.1 Temporal Holdout Validation

The fundamental validation strategy is **temporal holdout**: train on older data, test on newer data where outcomes are known.

```
Training window                      Test window
──────────────────────────────|──────┬───────────────
Jan 2024 – Dec 2025           | Jan 2026 – present
                              |      ↓
                              | Known outcomes for
                              | 200+ completed placements
```

For each test placement:

1. We observe the real intervention that occurred (e.g., a school change in week 8).
2. We query the twin at week 7: *"What is the effect of changing this child's school?"*
3. We compare the twin's CATE estimate to the actual difference in outcome between the treated child and a matched control (propensity score matching on pre-treatment features).

```python
def temporal_holdout_validation():
    train_data = placements.query("placement_end < '2026-01-01'")
    test_data = placements.query("placement_end >= '2026-01-01'")

    cf = CausalForest().fit(train_data.Y, train_data.T, train_data.X, train_data.W)

    metrics = {"bias": [], "coverage": [], "interval_width": []}
    for _, row in test_data.iterrows():
        cate_est = cf.effect(row[X_features].values.reshape(1, -1))
        ci = cf.effect_interval(row[X_features].values.reshape(1, -1), alpha=0.05)

        # Compare against matched control
        control = match_control(row, train_data)
        actual_effect = row["outcome"] - control["outcome"]

        metrics["bias"].append(cate_est - actual_effect)
        metrics["coverage"].append(ci[0] <= actual_effect <= ci[1])
        metrics["interval_width"].append(ci[1] - ci[0])

    return {
        "mean_bias": np.mean(metrics["bias"]),
        "empirical_coverage": np.mean(metrics["coverage"]),  # Target: 0.90–0.95
        "mean_interval_width": np.mean(metrics["interval_width"]),
        "mse": np.mean(np.square(metrics["bias"])),
    }
```

**Acceptance criteria** (weekly automated run):

| Metric | Target | Blocking |
|---|---|---|
| Empirical coverage (90% CI) | 0.85–0.95 | < 0.80 |
| Mean bias | within ±0.05 | > ±0.10 |
| Coverage by demographic group | within ±0.05 of overall | > ±0.10 for any group |
| Interval width | stable ±20% week-over-week | > 50% increase |

### 4.2 Intervention-Specific Validation

Each intervention type is validated independently against known historical cases:

| Intervention | Historical n | Validation approach |
|---|---|---|
| School change | ~120 cases | Compare twin's CATE to actual outcome of children who changed schools vs. propensity-matched controls who did not |
| Placement change | ~80 cases | Same approach. Additional check: did the twin detect the *same* effect direction as the observed outcome? |
| Visitation frequency change | ~60 cases | Dose-response curve: expected monotonicity (more visits → lower risk). Test via Spearman correlation. |
| Therapy increase | ~45 cases | Smallest n. Use Bayesian hierarchical model to pool information across therapy types. |

### 4.3 Cross-Validation Within Training Data

Use **k-fold causal cross-validation** (a modification of the Athey-Imbens cross-validation for CATE):

```python
from econml.crossfit import CausalForestCV

# Honest cross-fitting: train on fold -i, predict CATE on fold i
cf_cv = CausalForestCV(n_folds=5, n_estimators=200, honest=True)
cf_cv.fit(Y, T, X, W)

# Evaluate: for each fold, compare CATE of treated vs. control in that fold
# using the "R-loss" criterion — lower is better
r_loss = cf_cv.score(Y, T, X, W)
```

The 5-fold CATE R-loss is reported in the model card for each model version. A worsening R-loss triggers retraining.

### 4.4 Backtesting on Historical "What-Ifs"

We construct **counterfactual validation sets** from historical placement records where a caseworker considered an intervention but did not implement it (captured in `check_ins.notes` keyword flags):

- "Considered changing school but decided against it" — keywords: `["consider", "school", "transfer", "decided against"]`
- "Family requested more visits" — keywords: `["request", "more", "visits", "frequency"]`

For these cases, we do not know the counterfactual outcome (the intervention didn't happen). But we can test *coherence*: the twin should predict that children whose caseworkers *considered* an intervention have higher CATE than children whose caseworkers never considered it. If not, the twin's effect estimates are not aligned with caseworker intuition, which is a red flag even if the model is statistically valid.

```python
def coherence_test(twin, historical_notes):
    considered = historical_notes.query(
        "notes.str.contains('consider|thought about|weighing', case=False)"
    )
    not_considered = historical_notes.query(
        "~notes.str.contains('consider|thought about|weighing', case=False)"
    )

    cate_considered = twin.cate(considered)
    cate_not_considered = twin.cate(not_considered)

    # Expect: cate_considered.mean() > cate_not_considered.mean()
    t_stat, p_value = ttest_ind(cate_considered, cate_not_considered, alternative="greater")
    return {"coherence_p_value": p_value, "coherent": p_value < 0.05}
```

### 4.5 Automated Weekly Validation Pipeline

```python
# workflows/temporal_worker.py — WeeklyFairnessWorkflow extension

@activity.defn(name="validate_twin_activity")
async def validate_twin_activity() -> dict:
    metrics = temporal_holdout_validation()
    coherence = coherence_test()
    r_loss = cf_cv.score(Y, T, X, W)

    status = "PASS"
    flags = []
    if metrics["empirical_coverage"] < 0.80:
        status = "BLOCK"
        flags.append("twin_coverage_degraded")
    if abs(metrics["mean_bias"]) > 0.10:
        status = "BLOCK"
        flags.append("twin_bias_exceeded")
    if not coherence["coherent"]:
        status = "REVIEW"
        flags.append("twin_coherence_failed")

    # Write to twin_validation_log (new table)
    await conn.execute(
        """
        INSERT INTO twin_validation_log
            (validated_at, model_version, coverage, mean_bias, mse,
             r_loss, coherence_p, status, flags)
        VALUES (NOW(), $1, $2, $3, $4, $5, $6, $7, $8::jsonb)
        """,
        model_version,
        metrics["empirical_coverage"],
        metrics["mean_bias"],
        metrics["mse"],
        r_loss,
        coherence["coherence_p_value"],
        status,
        json.dumps(flags),
    )
    return {"status": status, "metrics": metrics}
```

---

## 5. Architectural Summary

```
┌──────────────────────────────────────────────────────────────────┐
│                        Twin API Layer                             │
│  POST /api/twin/{child_id}/simulate                               │
│  GET  /api/twin/{child_id}/state                                  │
│  GET  /api/twin/validate                                          │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────┐
│                   Counterfactual Engine                            │
│                                                                   │
│  EconML CausalForest (primary estimator)                          │
│    - Handles continuous, binary, and multi-valued treatments      │
│    - Infinitesimal jackknife CIs                                  │
│    - Honest splitting + regularisation for sparse data            │
│                                                                   │
│  Double ML (fallback for compound treatments)                     │
│    - PolynomialFeatures interaction terms                         │
│    - Debias via cross-fitting                                     │
│                                                                   │
│  Sensitivity (causalml)                                           │
│    - Robustness value per simulation                              │
│    - Placebo + negative control automated tests                   │
│    - Leave-one-covariate-out influence                            │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────┐
│                    Feature & State Pipeline                        │
│                                                                   │
│  child_twin_states (current_features JSONB, updated weekly)       │
│  behavioural_drift_signals (weekly signal snapshots)              │
│  crisis_predictions (disruption probability history)              │
│  ml_decision_audit (all prior decisions for effect decomposition) │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────┐
│                  Validation & Monitoring                           │
│                                                                   │
│  Temporal holdout (weekly automated)                              │
│    - Coverage, bias, MSE by demographic group                     │
│    - BLOCK on coverage < 0.80                                     │
│                                                                   │
│  Coherence test (weekly)                                          │
│    - CATE should align with caseworker intuition                  │
│    - REVIEW on coherence failure                                  │
│                                                                   │
│  Cross-fit R-loss (per model version)                             │
│    - Worsening R-loss triggers retraining                          │
│                                                                   │
│  twin_validation_log (permanent record)                           │
│    - Every weekly validation result stored                        │
│    - Queried by compliance UI                                     │
└──────────────────────────────────────────────────────────────────┘
```

---

## 6. Dependency & Package Additions

| Package | Version | Purpose |
|---|---|---|
| `econml` | ≥0.14 | CausalForest, DML, DRLearner, refutation |
| `causalml` | ≥0.14 | Sensitivity analysis, Uplift metrics |
| `shap` | already exists | Feature importance for CATE models |
| `scikit-learn` | already exists | Base models, PolynomialFeatures, cross-validation |

No additional deep learning dependencies. The entire simulation engine runs on CPU with sklearn-based learners.
