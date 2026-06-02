# AI Fairness & Bias Audit — Complete Metric Specification

Five metric families that the Artifex dashboard must track, defined with formulas, thresholds, and foster care–specific violation examples.

---

## 0. Data Requirements

### Protected attributes tracked

| Attribute | Source column | Current status |
|---|---|---|
| Gender | `children.gender` | Exists |
| Race / ethnicity | `children.race` | **Needs migration** — `TEXT, nullable` |
| SES proxy | `children.fpl_percent` | **Needs migration** — Federal Poverty Level % at intake (`FLOAT, nullable`) |
| Zip code | `children.zip_code` | **Needs migration** — `TEXT, nullable` |
| Special needs | `children.special_needs` | Exists (bool) |
| Age group | `children.age` → bucket `{0–5, 6–12, 13–17}` | Computed |
| Emergency level | `children.emergency_level` | Exists |
| Caseworker ID | `placements.caseworker_id` | Exists |

### Prediction vs. outcome labels

| Label | Source | Status |
|---|---|---|
| Predicted risk score | `crisis_predictions.disruption_probability` | Exists |
| Predicted risk level | `crisis_predictions.risk_level` | Exists |
| Predicted positive (high-risk) | `risk_level IN ('high','critical')` | Computed |
| Actual outcome (disrupted) | `prediction_feedback.disruption` | **Needs migration** |
| Actual outcome (stable) | `prediction_feedback.outcome = 'stable'` | **Needs migration** |
| Placement match score | `placement_predictions.score` | Exists |
| Recommended family | `placement_predictions.recommended` | Exists |

### Migration DDL for new columns

```sql
ALTER TABLE children
  ADD COLUMN IF NOT EXISTS race           TEXT,
  ADD COLUMN IF NOT EXISTS fpl_percent    DOUBLE PRECISION,  -- Federal Poverty Level %
  ADD COLUMN IF NOT EXISTS zip_code       TEXT;

COMMENT ON COLUMN children.race IS 'Self-reported race/ethnicity. Collected at intake per AFCARS standards.';
COMMENT ON COLUMN children.fpl_percent IS 'Household income as % of Federal Poverty Level at time of removal. SES proxy.';
COMMENT ON COLUMN children.zip_code IS '3-digit ZIP code prefix of the child''s home of origin. Geographic SES proxy.';
```

---

## 1. Demographic Parity

**Question:** Are placement recommendations (high-risk labels / family match scores) independent of protected attributes?

### 1.1 High-Risk Label Disparity

| Property | Value |
|---|---|
| **Definition** | Max–min difference in `P(predicted high-risk \| group)` across all groups of a protected attribute. |
| **Formula** | `DP = max_g(P(Ŷ=1 \| G=g)) − min_g(P(Ŷ=1 \| G=g))` where `Ŷ=1` means `risk_level IN ('high','critical')`. |
| **Threshold** | `< 0.05` (5 percentage points). A difference of 5pp or more triggers a **REVIEW** flag. |
| **Min group size** | `n ≥ 20` per group. Smaller groups are shown but excluded from the PASS/REVIEW calculation. |

**Violation example:** Black children (n=45) have a 38% high-risk rate. White children (n=120) have a 22% high-risk rate. DP = 0.16 → **REVIEW**. The model disproportionately flags Black children as high-risk, even if it is equally accurate for both groups.

### 1.2 Match Score Parity

| Property | Value |
|---|---|
| **Definition** | Difference in mean placement match score assigned by the matching model across groups. |
| **Formula** | `Δmean_score = max_g(mean(score \| G=g)) − min_g(mean(score \| G=g))` |
| **Threshold** | `< 10` points (on a 0–100 scale). |
| **Min group size** | n ≥ 10 per group. |

**Violation example:** Children from zip codes in the lowest SES quartile receive a mean match score of 61/100, while the highest SES quartile receives 78/100. Δ = 17 → **REVIEW**. The model systematically assigns lower compatibility scores to low-SES children.

### 1.3 Per-Group Breakdown Table

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Demographic Parity                                        Status: REVIEW │
├─────────────────────────────────────────────────────────────────────────┤
│ Attribute      │ Groups                          │ DP    │ Threshold │
│ ─────────────────────────────────────────────────────────────────────── │
│ Race           │ Black 38% · White 22% · Hispanic 24% · Other 20% │ 0.16 │ 0.05 ✗ │
│ SES (FPL %)    │ Q1 35% · Q2 28% · Q3 24% · Q4 19%              │ 0.16 │ 0.05 ✗ │
│ Zip (prefix)   │ 606 (0.32) · 902 (0.28) · 100 (0.21) · …       │ 0.18 │ 0.05 ✗ │
│ Gender         │ F 28% · M 26% · O 30%                          │ 0.04 │ 0.05 ✓ │
│ Special needs  │ Yes 34% · No 24%                               │ 0.10 │ 0.05 ✗ │
│ Age group      │ 0–5: 18% · 6–12: 28% · 13–17: 36%             │ 0.18 │ 0.05 ✗ │
└─────────────────────────────────────────────────────────────────────────┘
```

### Dashboard visualisation

- **Forest plot** with point estimates and 95% CIs for each group, anchored at the population mean. Groups whose CI does not cross the mean line are flagged.
- **Treemap** of zip codes coloured by high-risk rate — geographic clusters of disparity are immediately visible.

---

## 2. Equalized Odds

**Question:** Does the model make different types of errors for different demographic groups? Two components: false positive rate parity and false negative rate parity.

### Prerequisites

Requires `prediction_feedback` table with ground-truth outcomes. Until n ≥ 50 feedback labels accumulate across all groups, this section shows **"Insufficient data — collecting feedback"**.

### 2.1 False Positive Rate Parity (FPR)

| Property | Value |
|---|---|
| **Definition** | Difference in FPR across groups. FPR = `P(Ŷ=1 \| Y=0)` — children who were predicted high-risk but did NOT disrupt. |
| **Formula** | `ΔFPR = max_g(FPR_g) − min_g(FPR_g)` |
| **Threshold** | `< 0.10` (10pp). Foster care context: a false positive means unnecessary intervention (therapy, monitoring escalation, potential placement disruption anxiety). |
| **Min group size** | n ≥ 10 per group with known outcomes. |

**Violation example:** Hispanic children have FPR = 0.32 (32% of stable placements were labelled high-risk). White children have FPR = 0.14. ΔFPR = 0.18 → **REVIEW**. The model over-flags Hispanic children for interventions they don't need, causing unnecessary surveillance.

### 2.2 False Negative Rate Parity (FNR)

| Property | Value |
|---|---|
| **Definition** | Difference in FNR across groups. FNR = `P(Ŷ=0 \| Y=1)` — children who disrupted but were predicted low/medium-risk. |
| **Formula** | `ΔFNR = max_g(FNR_g) − min_g(FNR_g)` |
| **Threshold** | `< 0.10` (10pp). Foster care context: a false negative means a missed opportunity to intervene before disruption. This is the more severe error type. |
| **Min group size** | n ≥ 10 per group with known outcomes. |

**Violation example:** Black children have FNR = 0.08 (only 8% of disrupted Black children were missed). White children have FNR = 0.24. ΔFNR = 0.16 → **REVIEW**. The model is better at catching Black children who will disrupt but misses White children who will disrupt, meaning White children receive fewer preventative interventions relative to their need.

### 2.3 Dashboard visualisation

```
┌────────────────────────────────────────────────────────────────────────┐
│ Equalized Odds (n=142 labelled placements)            Status: REVIEW   │
├────────────────────────────────────────────────────────────────────────┤
│                  FPR (false alarms)          FNR (missed crises)       │
│ Black        ████████████████░ 0.32 ✗    ████░░░░░░░░░░░ 0.08 ✓     │
│ White        ██████░░░░░░░░░░░ 0.14 ✓    ████████████░░░ 0.24 ✗     │
│ Hispanic     ██████████████░░░ 0.30 ✗    ██████░░░░░░░░░ 0.12 ✓     │
│ ─────────────────────────────────────────────────────────────────────  │
│ ΔFPR = 0.18 ✗  |  ΔFNR = 0.16 ✗                                     │
│                                                                        │
│ ⋮ One group's FPR exceeds threshold                                   │
│ ⋮ One group's FNR exceeds threshold                                   │
└────────────────────────────────────────────────────────────────────────┘
```

- **Paired bar chart** per group: two bars (FPR left, FNR right). Threshold line at 0.10. Red bars exceed threshold.
- **Confusion matrix** per group in expandable rows.

---

## 3. Calibration

**Question:** Does a risk score of 70 mean the same probability of disruption for every demographic group?

### 3.1 Calibration by Group

| Property | Value |
|---|---|
| **Definition** | For each decile bin of predicted risk, the actual disruption rate should match the predicted rate within each group. |
| **Formula** | For bin b and group g: `CalibrationError_bg = |mean(Y \| score ∈ bin_b, G=g) − mean(score ∈ bin_b, G=g)|`. Aggregate: `ECE_g = Σ_b (w_b · |Y_rate_bg − pred_bg|)` where w_b = bin_b proportion. |
| **Threshold** | `< 0.05` ECE (Expected Calibration Error) per group. Max ECE across groups ≤ 0.08. |
| **Min group size** | n ≥ 30 per group with known outcomes. |

**Violation example:** For Black children, predicted scores of 70–79 correspond to an actual disruption rate of 52%. For White children, scores of 70–79 correspond to an actual disruption rate of 74%. ECE_Black = 0.11, ECE_White = 0.03. Max ECE = 0.11 > 0.08 → **REVIEW**. A score of 70 under-estimates risk for White children and over-estimates risk for Black children.

### 3.2 Reliability Curves

```
      1.0 ┤
          │
      0.8 ┤      ╱╲
          │     ╱  ╲      ── Perfect calibration (diagonal)
      0.6 ┤    ╱    ╲    ╌╌ Black children
          │   ╱     ╲    ─ White children
      0.4 ┤  ╱       ╲
          │ ╱         ╲
      0.2 ┤╱           ╲
          │
      0.0 ┼───┬───┬───┬───┬───
         0.0 0.2 0.4 0.6 0.8 1.0
               Predicted risk
```

**Interpretation:** Black children's curve above the diagonal between 0.4–0.7 means their actual disruption rate is higher than predicted → the model under-estimates risk in this range. White children's curve below the diagonal means the model over-estimates risk.

### 3.3 Dashboard visualisation

- **Reliability curve** per protected attribute, overlaid on a single chart. One line per group. 45° diagonal as reference.
- **ECE table** with per-group ECE, overall ECE, and max-ECE flag.
- **Drill-down:** Click a decile bin → list of all children in that bin with their actual outcomes.

---

## 4. Individual Fairness

**Question:** Do similar children receive similar placement recommendations and risk scores?

### 4.1 Consistency Score

| Property | Value |
|---|---|
| **Definition** | For each child, find their k-nearest neighbours (based on non-protected attributes). Measure the variance in risk scores among neighbours. A high variance means the model is inconsistent — similar children get different scores. |
| **Formula** | `Consistency = 1 − (1/N) Σ_i Σ_{j∈NN_k(i)} |score_i − score_j| / (k · range(scores))` |
| **Threshold** | `≥ 0.85` (85% consistent). Below 0.85 triggers REVIEW. |
| **Distance metric** | Euclidean distance over: age, special_needs, sibling_group, emergency_level, weeks_in_placement (all normalised to [0,1]). Protected attributes (race, gender, zip code, SES) are **excluded** from distance computation. |

### 4.2 Nearest-Neighbour Disparity

| Property | Value |
|---|---|
| **Definition** | The fraction of children whose risk score differs by more than 15 points from the median of their k-NN neighbourhood. |
| **Formula** | `NND = (1/N) Σ_i 𝕀(|score_i − median({score_j for j∈NN_k(i)})| > 15)` |
| **Threshold** | `< 0.10` (fewer than 10% of children are outliers relative to their similarity cluster). |

**Violation example:** Two 9-year-old girls with no siblings, both in emergency placement for 14 weeks, no special needs. CH-A0427 receives risk score 72. CH-B0318 receives risk score 34. Their similarity distance is 0.08 (nearly identical). Score gap = 38 points → NND flagged. **REVIEW.** The model is inconsistently applying risk to near-identical cases.

### 4.3 Dashboard visualisation

```
┌────────────────────────────────────────────────────────────────────────┐
│ Individual Fairness                                    Status: REVIEW  │
├────────────────────────────────────────────────────────────────────────┤
│ Consistency Score: 0.74 ✗ (threshold: ≥ 0.85)                        │
│ NN Disparity:      0.18 ✗ (threshold: < 0.10)                        │
│                                                                        │
│ Outlier children (score differs >15 from neighbourhood median):       │
│ ┌──────────────────────────────────────────────────────────────────┐ │
│ │ Child       │ Score │ Neighbourhood median │ Gap  │ Similarity │ │
│ │ CH-A0427    │ 72    │ 41                   │ +31  │ 0.92       │ │
│ │ CH-C0512    │ 18    │ 45                   │ −27  │ 0.88       │ │
│ │ CH-D3091    │ 81    │ 52                   │ +29  │ 0.91       │ │
│ └──────────────────────────────────────────────────────────────────┘ │
│                                                                        │
│ [View similarity cluster for CH-A0427 →]                              │
└────────────────────────────────────────────────────────────────────────┘
```

- **t-SNE / UMAP scatter plot** of children in embedding space (non-protected features). Points coloured by risk score. Outliers (high NN disparity) circled in red.
- **Table of top-K outliers** with similarity distance, score gap, and a link to view the full neighbourhood.

---

## 5. Historical Bias Detection

**Question:** Is the model amplifying, matching, or reducing the biases present in historical placement data?

### 5.1 Bias Amplification Ratio

| Property | Value |
|---|---|
| **Definition** | Compare the disparity in model predictions to the disparity in historical outcomes. |
| **Formula** | `BAR_g = (DP_model_g) / (DP_historical_g)` where DP_model is the demographic parity (high-risk rate) between group g and the reference group, and DP_historical is the actual disruption rate disparity in the training data. |
| **Interpretation** | BAR = 1.0 → model matches historical bias. BAR > 1.0 → model amplifies historical bias. BAR < 1.0 → model reduces historical bias. |
| **Threshold** | `BAR ≤ 1.0` — the model must never amplify. BAR > 1.0 triggers **REVIEW** and blocks deployment. |

**Example:**
- Historical: Black children disrupted at 28%, White children at 18% → DP_historical = 0.10.
- Model: Black children predicted high-risk at 38%, White children at 22% → DP_model = 0.16.
- `BAR = 0.16 / 0.10 = 1.6` → **REVIEW**. The model amplifies the original 10pp disparity into a 16pp disparity.

### 5.2 Feedback Loop Detection

| Property | Value |
|---|---|
| **Definition** | Track how demographic parity changes over successive retraining cycles (weekly). A widening trend means the feedback loop is entrenching bias. |
| **Formula** | `DP_trend = slope(DP over last 8 weekly retrains)`. Positive slope = disparity is growing. |
| **Threshold** | `|DP_trend| < 0.005` per week. Slope ≥ 0.005/wk for 3 consecutive weeks triggers **REVIEW**. |

**Violation example:** DP starts at 0.06, then 0.08, 0.11, 0.14 over four weekly retrains. DP_trend = +0.027/wk >> 0.005/wk → **REVIEW**. The retraining loop is snowballing bias.

### 5.3 Dashboard visualisation

```
┌────────────────────────────────────────────────────────────────────────┐
│ Historical Bias Detection                             Status: REVIEW   │
├────────────────────────────────────────────────────────────────────────┤
│ Bias Amplification Ratio (BAR)                                         │
│ ┌──────────────────────────────────────────────────────────────────┐  │
│ │ Attribute      │ Historical DP │ Model DP │ BAR   │              │  │
│ │ Race           │ 0.10          │ 0.16      │ 1.60✗ │[████████]  │  │
│ │ SES (FPL Q1vQ4)│ 0.12          │ 0.15      │ 1.25✗ │[██████░░]  │  │
│ │ Gender         │ 0.03          │ 0.04      │ 1.33✗ │[██████░░]  │  │
│ └──────────────────────────────────────────────────────────────────┘  │
│                                                                        │
│ Feedback Loop Trend                                                    │
│ DP over last 8 weekly retrains:                                        │
│ 0.10  0.11  0.11  0.12  0.14  0.15  0.16  0.18                       │
│ ░░░   ░░░   ░░░   ▒▒▒   ▒▒▒   ███   ███   ███   → slope +0.011 ⚠    │
│                                                                        │
│ [Historical baseline: training data from 2024–2025 (n=1,240)]          │
└────────────────────────────────────────────────────────────────────────┘
```

- **Waterfall chart** showing Historical DP → Model DP per attribute, with direction arrows (↗ = amplified, ↘ = reduced).
- **Sparkline** of DP over time (weekly retrains) with a trend line. Red background if slope exceeds threshold.
- **Callout** when a new retrain widens DP: "Warning: This week's retrain increased race disparity by 2pp. Consider adjusting sample weights."

---

## 6. Dashboard Implementation Plan

### 6.1 Backend

New endpoint replacing the existing simplistic `GET /api/fairness/metrics`:

```
GET /api/fairness/audit
  Query: ?group_by=race&group_by=ses&group_by=zip&group_by=gender
  Response:
    demographic_parity: { metrics: {...}, breakdowns: {...}, status, threshold }
    equalized_odds:     { fpr: {...}, fnr: {...}, status, min_group_n }
    calibration:        { ece_by_group: {...}, reliability_curves: [...], status }
    individual_fairness:{ consistency_score, nn_disparity, outliers: [...], status }
    historical_bias:    { bar: {...}, dp_trend, status }
    meta:               { total_placements, total_feedback_labels, as_of }
```

### 6.2 Frontend

New `FairnessAuditDashboard.tsx` component with five tabbed panels:

```
┌────────────────────────────────────────────────────────────────────────┐
│ Fairness & Bias Audit                          Overall: ⚠ 2 of 5 REVIEW │
├────────────────────────────────────────────────────────────────────────┤
│ [Demographic Parity] [Equalized Odds] [Calibration] [Individual] [History] │
│                                                                         │
│ (tab content here)                                                      │
│                                                                         │
│ Each tab shows: metric card + visualisation + violation table           │
│ Footer: "Last audited: 2026-06-01 06:00 UTC · n=214 placements"       │
└────────────────────────────────────────────────────────────────────────┘
```

### 6.3 Alerting

| Condition | Alert |
|---|---|
| Any metric enters REVIEW | Dashboard banner + optional Slack #fairness channel |
| BAR > 1.0 | Blocks automated retraining pipeline. Requires ML engineer sign-off. |
| DP_trend positive for 3 consecutive weeks | Schedule fairness review meeting. Generate disparity report. |
| Individual consistency < 0.80 | Flag to model team: check feature engineering for omitted interaction terms. |

### 6.4 Reporting Cadence

| Frequency | Report |
|---|---|
| **Weekly** (auto) | Computed after each retrain. Stored in `fairness_audit_log` table. |
| **Monthly** (review) | Full PDF report with all five metric families, trend charts, and violation summary. Archived for regulatory compliance. |
| **Quarterly** (deep) | Retrospective analysis: compare model disparities to AFCARS county-level data. Check if BAR is changing over time. |
| **Annual** (regulatory) | Submit to state oversight board. Include all five metric families, intervention records, and caseworker feedback themes. |

---

## 7. Metric Quick-Reference Card

| Metric | Type | Threshold | Data needed | Min n | Status flag |
|---|---|---|---|---|---|
| Demographic parity — high-risk label | Disparity | DP < 0.05 | Predicted risk level | 20/group | REVIEW |
| Demographic parity — match score | Disparity | Δmean < 10 pts | Match score | 10/group | REVIEW |
| FPR parity | Disparity | ΔFPR < 0.10 | Predicted + actual outcomes | 10/group | REVIEW |
| FNR parity | Disparity | ΔFNR < 0.10 | Predicted + actual outcomes | 10/group | REVIEW |
| Calibration (ECE) | Accuracy | ECE < 0.08 max | Predicted score + actual outcomes | 30/group | REVIEW |
| Individual consistency | Consistency | ≥ 0.85 | Risk scores + non-protected features | N/A | REVIEW |
| NN disparity | Disparity | < 0.10 | Risk scores + non-protected features | N/A | REVIEW |
| Bias amplification ratio | Ratio | BAR ≤ 1.0 | Model predictions + historical outcomes | 50 total | BLOCK |
| Feedback loop trend | Trend | slope < 0.005/wk | 8 weekly DP values | 8 weeks | REVIEW |

---

## 8. Implementation Order

| Phase | Metrics | Timeline |
|---|---|---|
| **Phase 1** (now) | Demographic parity, SHAP explainability, historical baseline | 1 sprint |
| **Phase 2** (next) | Individual fairness, feedback loop trend, alerting | 1 sprint |
| **Phase 3** (after n≥50 feedback labels) | Equalized odds, calibration | 1 sprint |
| **Phase 4** (ongoing) | Race / SES / zip code data collection, quarterly reports | Continuous |

The Phase 1 metrics are already partially implemented in `api/routes/fairness.py` and `FairnessDashboard.tsx`. The existing code measures only high-risk rate disparity across gender / special needs / emergency level. This specification expands to 10 tracked metrics across 5 families, adds race/SES/zip as protected attributes, and introduces the BAR gating mechanism that can block the retraining pipeline.
