# Predictive Crisis Engine — ML Pipeline Specification

Forecasts placement disruption (unplanned removal of a child from a foster placement) 2–4 weeks in advance by fusing **behavioural drift signals** with **static placement features**.

---

## 1. Feature Engineering

### 1.1 Data Sources

| Source | Table | Update cadence |
|---|---|---|
| Behavioural drift snapshot | `behavioural_drift_signals` | Weekly (every Monday) |
| Placement snapshot | `placements` | Continuous |
| Child demographics | `children` | Static (updated on change) |
| Placement history | `placement_history` | Event-driven |
| Crisis predictions | `crisis_predictions` (previous rows) | Weekly |

### 1.2 Feature Vector

Each training example is a **placement-week**: one row per child-placement per calendar week.

#### Static features (from `children` + `placements`)

| Feature | Type | Source |
|---|---|---|
| `age` | int | children.age |
| `age_group` | str bucket | {0–5, 6–12, 13–17} |
| `special_needs` | bool | children.special_needs |
| `sibling_present` | bool | children.sibling_group |
| `intake_reason_*` | 11 one-hot dummies | children.intake_reason |
| `placement_week` | int | weeks since placement start |
| `disruption_rate_similar` | float | historical disruption % for age±2 × special_needs cohort |
| `placement_transitions_last_12m` | int | count of prior placements in last year |

#### Drift signal features (from `behavioural_drift_signals`)

All five domains produce **four feature types** per signal:

| Type | Description | Example (school_attendance) |
|---|---|---|
| **Level** | Current-period raw aggregate | `school_attendance_rate` = 0.70 |
| **Trend** | Slope over the 28d window | `school_attendance_trend` = −0.08 |
| **Delta** | Deviation from placement baseline | `school_attendance_delta` = −0.22 |
| **Volatility** | Std-dev of weekly values in window | `school_attendance_volatility` = 0.12 |

Total: 5 signals × 4 types = **20 drift features**.

Category-flagged features (e.g. `keyword_flags`, `dominant_flags`, `school_engagement_flags`, `communication_channels`) are count-encoded or TF-binarised:

| Derived feature | How |
|---|---|
| `visit_flag_count_total` | sum of all keyword flags across entries |
| `incident_severity_critical_flag` | 1 if any incident severity ≥ 4 |
| `runway_ideation_flag` | 1 if "runaway_ideation" in any entry's keyword_flags |
| `medication_applies` | 0/1 gate (model must handle this) |
| `after_hours_ratio` | after_hours_contacts / outreach_attempts |

#### Lag features (temporal memory)

Because we use a feed-forward model (not RNN), temporal autocorrelation is injected explicitly:

| Lag feature | Definition |
|---|---|
| `{signal}_lag_1w` | Signal level value from 1 week ago |
| `{signal}_lag_2w` | Signal level value from 2 weeks ago |
| `{signal}_delta_1w` | Change from last week: level(t) − level(t−1) |
| `{drift_index}_lag_1w` | Composite drift index last week |
| `{drift_index}_acceleration` | drift_index_delta_1w − drift_index_delta_2w |

### 1.3 Missing-value policy

| Scenario | Treatment |
|---|---|
| `medication_compliance.applies = false` | Set all medication features to 0, add binary `medication_applies = 0` |
| First 4 weeks (no baseline yet) | Use population median as baseline proxy until 4 snapshots accumulate |
| Missing lag features (first snapshot) | Forward-fill from current value (lag = level) |

### 1.4 Complete feature count

~45–55 float/int features per row.

---

## 2. Model Choice

### Primary: XGBoost Classifier (gradient-boosted decision tree)

**Why not a deep sequence model (LSTM / Transformer):**

| Concern | Deep sequence | XGBoost |
|---|---|---|
| **Sample efficiency** | Needs 10k+ positive examples | Works well with ~200+ positives |
| **Interpretability** | Attention weights are noisy; SHAP on transformers is expensive | Native SHAP / `feature_importances_` in milliseconds |
| **Deployment** | GPU recommended, larger surface area | CPU-only, single joblib file |
| **Missing data** | Requires imputation pipeline | Native `missing=NaN` handling |
| **Temporal signal** | Handled internally | Injected via engineered lag features |

**Why not a pure rule-based system:**
- We already have a rule-based fallback (`crisis_predictor.py`). The goal is to learn non-linear interactions (e.g. "declining attendance + rising incident severity + falling medication compliance" = exponential risk, not additive).

**Why XGBoost over LightGBM / CatBoost:**
- XGBoost is already in the project's dependency tree (`xgboost==2.1.3`), used in two other models.
- CatBoost handles categoricals natively but adds a dependency. We one-hot encode instead.
- LightGBM's leaf-wise growth can overfit on small disruption data. XGBoost's depth-wise growth is more conservative.

### Secondary (future): Stacking ensemble

After 12+ months of data (est. 5,000+ placement-weeks, 800+ disruptions), add a **GLM meta-learner** that blends:
- XGBoost probability
- Rule-based probability (`crisis_predictor.py` fallback score)
- Simple exponential-smoothing forecast of disruption probability from the child's own trajectory

The GLM (logistic regression with L2 regularisation) prevents overfitting and preserves interpretability.

### Fallback

The existing `crisis_predictor.py` rule-based predictor stays as cold-start / model-unavailable fallback. Its output is also logged as a feature for future stacking.

---

## 3. Training Approach

### 3.1 Label Definition

| Horizon | Label | Condition |
|---|---|---|
| 14 days | `y_14d` | 1 if placement_history.disruption = TRUE within 14 days of snapshot_date |
| 21 days | `y_21d` | 1 if disruption within 21 days |
| 28 days | `y_28d` | 1 if disruption within 28 days |

Train three separate models (or a multi-output model) for each horizon. The API serves `y_21d` by default.

**Censoring:** Snapshots where the placement ended non-disruptively (planned move, reunification) within the prediction window are excluded from training for that horizon. Snapshots where the placement is still active and no disruption occurred within the window are negative examples.

### 3.2 Train / Validation / Test Split

**Temporal split (not random).** Disruption is time-dependent; random splits leak future information into training.

| Split | Rows | Period |
|---|---|---|
| **Train** | 70% | Earliest 70% of snapshot dates |
| **Validation** | 15% | Middle 15% (tune hyperparameters, early stopping) |
| **Test** | 15% | Most recent 15% (final evaluation only, 1× per quarter) |

**Child-level grouping:** All snapshots for one child-placement must be in the same split. Enforced by splitting on `placement_id`.

### 3.3 Class Imbalance

Placement disruptions occur in ~15–25% of placements. In a weekly-snapshot dataset, positive labels are ~5–8% of rows (disruption is a single event per placement, but we have 14+ weekly snapshots per stable placement).

| Technique | How |
|---|---|
| `scale_pos_weight` | `sum(negative) / sum(positive)` — native XGBoost param |
| **Stratified CV** | `StratifiedKFold(n_splits=5)` on validation set |
| **Threshold tuning** | Maximise F2-score (recall-preferring) on validation. Disruption false negatives are costlier than false positives. |
| **No synthetic oversampling** | SMOTE adds noise on rare-event tabular data. Prefer `scale_pos_weight` + threshold tuning. |

### 3.4 Hyperparameter Grid

```yaml
n_estimators: 500 (early stopping at 50 rounds)
max_depth: [3, 4, 6]
learning_rate: [0.01, 0.05, 0.1]
subsample: [0.7, 0.8, 1.0]
colsample_bytree: [0.7, 0.8, 1.0]
min_child_weight: [1, 3, 5]
scale_pos_weight: [computed, computed*2, computed/2]
```

Use `optuna` or `GridSearchCV` with 5-fold stratified CV on the validation set, optimising for **validation AUC-PR** (not AUC-ROC — PR is sensitive to class imbalance).

### 3.5 Model Outputs

| Artifact | Format | Location |
|---|---|---|
| Trained XGBoost | `joblib` | `models/crisis_drift_model.pkl` |
| Feature column order | `JSON` | `models/crisis_drift_features.json` |
| Feature metadata | `JSON` | `models/crisis_drift_metadata.json` (dtypes, imputation values, one-hot mapping) |
| Thresholds | `JSON` | `models/crisis_drift_thresholds.json` (optimal threshold per horizon) |

---

## 4. Prediction Output Format

The inference endpoint (`GET /api/placements/{placement_id}/crisis-prediction`) returns:

```json
{
  "placement_id": "foster-CH-A0427",
  "child_id": "CH-A0427",
  "prediction_date": "2026-06-01T06:00:00Z",
  "prediction_horizon_days": 21,

  "risk_score": 72.4,
  "risk_level": "high",
  "confidence_interval_95": [61.2, 82.1],

  "top_contributing_features": [
    {
      "feature": "incident_severity_trend",
      "shap_value": 14.3,
      "direction": "increasing_severity",
      "description": "Incident severity has been rising over the past 4 weeks"
    },
    {
      "feature": "school_attendance_delta",
      "shap_value": -11.8,
      "direction": "declining_attendance",
      "description": "School attendance is 22% below this child's baseline"
    },
    {
      "feature": "caseworker_sentiment_delta",
      "shap_value": -9.2,
      "direction": "deteriorating_rapport",
      "description": "Caseworker visit sentiment is declining (avg −0.60 from baseline)"
    }
  ],

  "drift_signals_breakdown": {
    "school_attendance":      {"risk_contribution": 18.2, "status": "drifting"},
    "caseworker_sentiment":   {"risk_contribution": 15.7, "status": "drifting"},
    "incident_frequency":     {"risk_contribution": 22.1, "status": "critical"},
    "incident_severity":      {"risk_contribution": 19.4, "status": "drifting"},
    "medication_compliance":  {"risk_contribution": 11.8, "status": "drifting"},
    "communication_lag":      {"risk_contribution": 9.2,  "status": "drifting"},
    "communication_tone":     {"risk_contribution": 6.3,  "status": "stable"}
  },

  "recommended_interventions": [
    "Schedule urgent therapy review — runaway ideation flagged",
    "Increase caseworker visits to weekly — sentiment declining",
    "Initiate school liaison meeting — attendance 22% below baseline",
    "Assign mentor support — multiple critical incidents in last 7 days"
  ],

  "model_version": "crisis_drift_v2.3",
  "feature_hash": "a1b2c3d4e5"
}
```

### Confidence interval estimation

Use **quantile regression forests** (`XGBoost quantile` objective with `alpha=0.025` and `alpha=0.975` trained alongside the mean model). Two auxiliary models predict the 2.5th and 97.5th percentiles. At inference:
- `confidence_interval_95 = [q2_model.predict(features), q98_model.predict(features)]`

Fallback when quantile models unavailable: bootstrap 100 rounds with `subsample=0.8` on the main model, report 2.5/97.5 percentiles of the 100 predictions.

### Top-3 contributing features

Computed via **TreeSHAP** (`shap.TreeExplainer`). The `shap_value` is the mean absolute SHAP value for that feature across the ensemble. The `direction` label maps the sign of the SHAP interaction to a human-readable string based on the feature's known semantics (e.g. negative delta on attendance → "declining_attendance").

---

## 5. Retraining Cadence

| Cadence | Trigger | Scope |
|---|---|---|
| **Weekly (auto)** | Monday 02:00 UTC, cron | Re-fit the primary XGBoost on all available data (up to the previous week). Re-compute baselines for all active placements. Update thresholds. |
| **On-demand (manual)** | `make train-crisis-drift` | Triggered after a drift-signal schema change, data-quality fix, or hyperparameter update. |
| **Quarterly (review)** | Calendar quarter | Full eval on holdout test set. Re-fit quantile regression models. Re-tune hyperparameters via Optuna. Update feature metadata. Decide if stacking ensemble should be activated. |
| **Model retirement** | AUC-PR drops >5pp from baseline | Roll back to previous model version, page ML engineer. |

### Model versioning

| Pattern | Example |
|---|---|
| Artifact path | `models/archive/crisis_drift_v{major}.{minor}.pkl` |
| `model_version` in output | `crisis_drift_v2.3` |
| Git tag | `crisis-drift-v2.3` |
| Retention | Keep last 12 monthly snapshots; archive quarterly for 2 years |

### Automated pipeline (Temporal workflow)

```
Scheduled cron (weekly)
  └── trigger_training_workflow
       ├── activity: query_labels (fetch disruptions from placement_history)
       ├── activity: build_feature_matrix (join behavioural_drift_signals + children + placements)
       ├── activity: train_test_split (temporal split, child-level grouping)
       ├── activity: train_xgboost (with Optuna hyperparameter search)
       ├── activity: train_quantile_models (for confidence intervals)
       ├── activity: evaluate (AUC-PR, F2, calibration curve on validation set)
       ├── activity: update_thresholds (maximise F2 on validation)
       ├── activity: persist_model (joblib dump + feature list)
       └── activity: notify (Slack #ml-alerts: AUC-PR, drift in feature distributions)
```

---

## 6. Evaluation Criteria

| Metric | Target | Why |
|---|---|---|
| **AUC-PR** (validation) | ≥ 0.55 | Primary metric — sensitive to rare-class performance |
| **AUC-ROC** (validation) | ≥ 0.80 | Secondary — general separability |
| **F2-score** (validation) | ≥ 0.45 | Favours recall over precision (missed disruptions are costly) |
| **Brier score** | ≤ 0.12 | Calibration — predicted probabilities should match observed frequencies |
| **Mean confidence interval width** | ≤ 25 points | CI must be narrow enough to be operationally useful |
| **Feature stability** | Population SHAP distributions do not shift >0.5 IQR | Detects data drift without waiting for label drift |

All thresholds are **starting targets** for the initial cohort of ~500 placements. Rebaseline after 6 months of production data.
