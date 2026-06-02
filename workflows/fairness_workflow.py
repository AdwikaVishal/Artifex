"""
fairness_workflow.py – Weekly fairness audit Temporal workflow.

Cron-triggered every Monday 03:00 UTC.  Computes all 9 fairness metrics
from ml_decision_audit and prediction_feedback and stores the result
in fairness_audit_log for dashboard consumption and regulatory compliance.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Any

import structlog
from temporalio import activity, workflow

logger = structlog.get_logger()


@activity.defn(name="compute_fairness_metrics_activity")
async def compute_fairness_metrics_activity() -> dict[str, Any]:
    """
    Compute all 9 fairness metric families from ml_decision_audit
    and prediction_feedback for the past 7 days, then write the
    aggregate result to fairness_audit_log.

    Returns the written row as a dict for workflow visibility.
    """
    import asyncpg

    db_url = os.getenv(
        "DATABASE_URL", "postgresql://artifex:artifex123@postgres:5432/placements"
    )
    conn = await asyncpg.connect(db_url, timeout=5.0)
    try:
        report_week = datetime.utcnow().date() - timedelta(days=7)

        # ── Latest model version in the audit log ──────────────────────────────
        model_row = await conn.fetchrow(
            "SELECT model_version FROM ml_decision_audit ORDER BY id DESC LIMIT 1"
        )
        model_version = model_row["model_version"] if model_row else "unknown"

        # ── 1. Demographic parity ──────────────────────────────────────────────
        # P(high-risk | group) for crisis_prediction decisions in the past 7 days
        dp_metrics: dict[str, float | None] = {
            "dp_race": None,
            "dp_ses": None,
            "dp_gender": None,
            "dp_special_needs": None,
            "dp_age_group": None,
        }

        demographics_fields = [
            ("dp_race", "race"),
            ("dp_gender", "gender"),
            ("dp_special_needs", "special_needs"),
        ]
        for metric_key, demo_field in demographics_fields:
            rows = await conn.fetch(
                """
                SELECT
                    child_demographics->>$2 AS grp,
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE output_score >= 60) AS high_risk
                FROM ml_decision_audit
                WHERE decision_type IN ('crisis_prediction', 'risk_score')
                  AND decided_at >= NOW() - INTERVAL '7 days'
                  AND child_demographics->>$2 IS NOT NULL
                GROUP BY grp
                """,
                report_week.isoformat(),
                demo_field,
            )
            groups = [dict(r) for r in rows if int(r["total"]) >= 20]
            if len(groups) >= 2:
                rates = [g["high_risk"] / g["total"] for g in groups]
                dp_metrics[metric_key] = round(max(rates) - min(rates), 4)

        # SES proxy (dp_ses): fpl_percent quartiles
        ses_rows = await conn.fetch(
            """
            SELECT
                CASE
                    WHEN (child_demographics->>'fpl_percent')::FLOAT < 50 THEN 'Q1'
                    WHEN (child_demographics->>'fpl_percent')::FLOAT < 100 THEN 'Q2'
                    WHEN (child_demographics->>'fpl_percent')::FLOAT < 150 THEN 'Q3'
                    ELSE 'Q4'
                END AS grp,
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE output_score >= 60) AS high_risk
            FROM ml_decision_audit
            WHERE decision_type IN ('crisis_prediction', 'risk_score')
              AND decided_at >= NOW() - INTERVAL '7 days'
              AND child_demographics->>'fpl_percent' IS NOT NULL
              AND (child_demographics->>'fpl_percent')::FLOAT >= 0
            GROUP BY grp
            """
        )
        ses_groups = [dict(r) for r in ses_rows if int(r["total"]) >= 20]
        if len(ses_groups) >= 2:
            ses_rates = [g["high_risk"] / g["total"] for g in ses_groups]
            dp_metrics["dp_ses"] = round(max(ses_rates) - min(ses_rates), 4)

        # Age group
        age_rows = await conn.fetch(
            """
            SELECT
                CASE
                    WHEN (child_demographics->>'age')::INT <= 5 THEN '0-5'
                    WHEN (child_demographics->>'age')::INT <= 12 THEN '6-12'
                    ELSE '13-17'
                END AS grp,
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE output_score >= 60) AS high_risk
            FROM ml_decision_audit
            WHERE decision_type IN ('crisis_prediction', 'risk_score')
              AND decided_at >= NOW() - INTERVAL '7 days'
              AND child_demographics->>'age' IS NOT NULL
            GROUP BY grp
            """
        )
        age_groups = [dict(r) for r in age_rows if int(r["total"]) >= 20]
        if len(age_groups) >= 2:
            age_rates = [g["high_risk"] / g["total"] for g in age_groups]
            dp_metrics["dp_age_group"] = round(max(age_rates) - min(age_rates), 4)

        # ── 2. Equalized odds (requires prediction_feedback labels) ──────────
        fpr_disparity: float | None = None
        fnr_disparity: float | None = None
        feedback_count = await conn.fetchval(
            "SELECT COUNT(*) FROM prediction_feedback"
        )
        if feedback_count and int(feedback_count) >= 50:
            eo_rows = await conn.fetch(
                """
                SELECT
                    m.child_demographics->>'race' AS grp,
                    COUNT(*) FILTER (
                        WHERE m.output_score >= 60 AND pf.outcome = 'stable'
                    ) AS fp,
                    COUNT(*) FILTER (
                        WHERE m.output_score < 60 AND pf.outcome = 'disrupted'
                    ) AS fn,
                    COUNT(*) FILTER (WHERE pf.outcome = 'stable') AS total_stable,
                    COUNT(*) FILTER (WHERE pf.outcome = 'disrupted') AS total_disrupted
                FROM ml_decision_audit m
                JOIN prediction_feedback pf ON pf.placement_id = m.placement_id
                WHERE m.decision_type IN ('crisis_prediction', 'risk_score')
                  AND pf.submitted_at >= NOW() - INTERVAL '90 days'
                GROUP BY grp
                """
            )
            eo_groups = [dict(r) for r in eo_rows
                         if int(r["total_stable"]) >= 10 and int(r["total_disrupted"]) >= 10]
            if len(eo_groups) >= 2:
                fprs = [g["fp"] / g["total_stable"] for g in eo_groups]
                fnrs = [g["fn"] / g["total_disrupted"] for g in eo_groups]
                fpr_disparity = round(max(fprs) - min(fprs), 4)
                fnr_disparity = round(max(fnrs) - min(fnrs), 4)

        # ── 3. Calibration (max ECE) ──────────────────────────────────────────
        max_ece: float | None = None
        if feedback_count and int(feedback_count) >= 30:
            cal_rows = await conn.fetch(
                """
                SELECT
                    m.child_demographics->>'race' AS grp,
                    m.output_score,
                    pf.outcome
                FROM ml_decision_audit m
                JOIN prediction_feedback pf ON pf.placement_id = m.placement_id
                WHERE m.decision_type IN ('crisis_prediction', 'risk_score')
                  AND pf.submitted_at >= NOW() - INTERVAL '90 days'
                  AND m.output_score IS NOT NULL
                """
            )
            if cal_rows:
                ece_by_group: dict[str, list[float]] = {}
                for r in cal_rows:
                    grp = r["grp"] or "unknown"
                    ece_by_group.setdefault(grp, []).append(
                        (float(r["output_score"]), 1.0 if r["outcome"] == "disrupted" else 0.0)
                    )
                ece_values: list[float] = []
                for grp, pairs in ece_by_group.items():
                    if len(pairs) < 30:
                        continue
                    n = len(pairs)
                    scores = [p[0] for p in pairs]
                    outcomes = [p[1] for p in pairs]
                    # Decile bins
                    total_ece = 0.0
                    for i in range(10):
                        lo = i * 10.0
                        hi = lo + 10.0
                        bin_idx = [j for j in range(n) if lo <= scores[j] < hi]
                        if not bin_idx:
                            continue
                        bin_n = len(bin_idx)
                        bin_pred = sum(scores[j] / 100.0 for j in bin_idx) / bin_n
                        bin_actual = sum(outcomes[j] for j in bin_idx) / bin_n
                        total_ece += (bin_n / n) * abs(bin_actual - bin_pred)
                    ece_values.append(total_ece)
                if ece_values:
                    max_ece = round(max(ece_values), 4)

        # ── 4. Individual fairness ────────────────────────────────────────────
        consistency: float | None = None
        nn_disparity: float | None = None
        ind_rows = await conn.fetch(
            """
            SELECT child_id, output_score,
                   child_demographics->>'age' AS age,
                   child_demographics->>'special_needs' AS special_needs,
                   child_demographics->>'emergency_level' AS emergency_level
            FROM ml_decision_audit
            WHERE decision_type = 'crisis_prediction'
              AND decided_at >= NOW() - INTERVAL '7 days'
              AND output_score IS NOT NULL
            """
        )
        if len(ind_rows) >= 10:
            children_data: list[dict[str, Any]] = []
            for r in ind_rows:
                age = r["age"]
                sn = r["special_needs"]
                el = r["emergency_level"]
                if age is None or sn is None or el is None:
                    continue
                children_data.append({
                    "child_id": r["child_id"],
                    "score": float(r["output_score"]),
                    "age": int(age),
                    "special_needs": 1 if sn == "true" or sn is True else 0,
                    "emergency_level": {"normal": 0, "elevated": 1, "emergency": 2}.get(
                        str(el).lower(), 0
                    ),
                })
            if len(children_data) >= 10:
                k = min(5, max(2, len(children_data) // 2))
                total_consistency = 0.0
                outlier_count = 0
                n = len(children_data)
                for i, c1 in enumerate(children_data):
                    distances: list[tuple[float, float]] = []
                    for j, c2 in enumerate(children_data):
                        if i == j:
                            continue
                        d = (
                            ((c1["age"] - c2["age"]) / 17.0) ** 2
                            + (c1["special_needs"] - c2["special_needs"]) ** 2
                            + (c1["emergency_level"] - c2["emergency_level"]) ** 2
                        ) ** 0.5
                        distances.append((d, c2["score"]))
                    distances.sort(key=lambda x: x[0])
                    neighbours = distances[:k]
                    neighbour_scores = [ns for _, ns in neighbours]
                    median_score = sorted(neighbour_scores)[len(neighbour_scores) // 2]
                    gap = abs(c1["score"] - median_score)
                    if gap > 15:
                        outlier_count += 1
                    avg_nn_score = sum(neighbour_scores) / len(neighbour_scores)
                    total_consistency += abs(c1["score"] - avg_nn_score)

                score_range = max(c["score"] for c in children_data) - min(c["score"] for c in children_data)
                if score_range > 0:
                    consistency = round(1.0 - total_consistency / (n * k * score_range / 100.0), 4)
                    consistency = max(0.0, min(1.0, consistency))
                    nn_disparity = round(outlier_count / n, 4)

        # ── 5. Historical bias (BAR) ──────────────────────────────────────────
        bar_race: float | None = None
        bar_ses: float | None = None

        # Historical DP from placement_history (training data baseline)
        hist_rows = await conn.fetch(
            """
            SELECT
                c.race AS grp,
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE ph.disruption = TRUE) AS disrupted
            FROM placement_history ph
            JOIN children c ON c.child_id = ph.child_id
            WHERE c.race IS NOT NULL
            GROUP BY c.race
            """
        )
        hist_groups = [dict(r) for r in hist_rows if int(r["total"]) >= 20]
        if len(hist_groups) >= 2 and dp_metrics["dp_race"] is not None:
            hist_rates = [g["disrupted"] / g["total"] for g in hist_groups]
            hist_dp = round(max(hist_rates) - min(hist_rates), 4)
            if hist_dp > 0:
                bar_race = round(dp_metrics["dp_race"] / hist_dp, 4)

        # BAR for SES
        hist_ses_rows = await conn.fetch(
            """
            SELECT
                CASE
                    WHEN c.fpl_percent < 50 THEN 'Q1'
                    WHEN c.fpl_percent < 100 THEN 'Q2'
                    WHEN c.fpl_percent < 150 THEN 'Q3'
                    ELSE 'Q4'
                END AS grp,
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE ph.disruption = TRUE) AS disrupted
            FROM placement_history ph
            JOIN children c ON c.child_id = ph.child_id
            WHERE c.fpl_percent IS NOT NULL AND c.fpl_percent >= 0
            GROUP BY grp
            """
        )
        hist_ses_groups = [dict(r) for r in hist_ses_rows if int(r["total"]) >= 20]
        if len(hist_ses_groups) >= 2 and dp_metrics["dp_ses"] is not None:
            hist_ses_rates = [g["disrupted"] / g["total"] for g in hist_ses_groups]
            hist_ses_dp = round(max(hist_ses_rates) - min(hist_ses_rates), 4)
            if hist_ses_dp > 0:
                bar_ses = round(dp_metrics["dp_ses"] / hist_ses_dp, 4)

        # ── Determine flags and overall status ─────────────────────────────────
        flags: list[str] = []
        thresholds = {
            "dp_race": (0.05, 0.10),
            "dp_ses": (0.05, 0.10),
            "dp_gender": (0.05, 0.10),
            "dp_special_needs": (0.05, 0.10),
            "dp_age_group": (0.05, 0.10),
            "fpr_disparity": (0.10, 0.15),
            "fnr_disparity": (0.10, 0.20),
        }
        for metric, (amber, red) in thresholds.items():
            val = None
            if metric in dp_metrics:
                val = dp_metrics[metric]
            elif metric == "fpr_disparity":
                val = fpr_disparity
            elif metric == "fnr_disparity":
                val = fnr_disparity
            if val is not None and val >= amber:
                flags.append(f"{metric}_exceeded")

        if bar_race is not None and bar_race > 1.0:
            flags.append("bar_race_amplification")
        if bar_ses is not None and bar_ses > 1.0:
            flags.append("bar_ses_amplification")
        if consistency is not None and consistency < 0.85:
            flags.append("consistency_below_threshold")

        if any("bar" in f for f in flags):
            overall_status = "BLOCK"
        elif flags:
            overall_status = "REVIEW"
        else:
            overall_status = "PASS"

        # ── Write to fairness_audit_log ────────────────────────────────────────
        await conn.execute(
            """
            INSERT INTO fairness_audit_log
                (report_week, model_version,
                 dp_race, dp_ses, dp_gender, dp_special_needs, dp_age_group,
                 fpr_disparity, fnr_disparity,
                 max_ece,
                 consistency, nn_disparity,
                 bar_race, bar_ses,
                 flags, overall_status)
            VALUES ($1, $2,
                    $3, $4, $5, $6, $7,
                    $8, $9,
                    $10,
                    $11, $12,
                    $13, $14,
                    $15::jsonb, $16)
            """,
            report_week,
            model_version,
            dp_metrics["dp_race"],
            dp_metrics["dp_ses"],
            dp_metrics["dp_gender"],
            dp_metrics["dp_special_needs"],
            dp_metrics["dp_age_group"],
            fpr_disparity,
            fnr_disparity,
            max_ece,
            consistency,
            nn_disparity,
            bar_race,
            bar_ses,
            json.dumps(flags),
            overall_status,
        )

        result = {
            "report_week": report_week.isoformat(),
            "model_version": model_version,
            "overall_status": overall_status,
            "flags": flags,
            "metrics": {
                "demographic_parity": dp_metrics,
                "equalized_odds": {
                    "fpr_disparity": fpr_disparity,
                    "fnr_disparity": fnr_disparity,
                },
                "calibration": {"max_ece": max_ece},
                "individual_fairness": {
                    "consistency": consistency,
                    "nn_disparity": nn_disparity,
                },
                "historical_bias": {
                    "bar_race": bar_race,
                    "bar_ses": bar_ses,
                },
            },
        }

        logger.info(
            "fairness.weekly_report_computed",
            report_week=report_week.isoformat(),
            status=overall_status,
            flag_count=len(flags),
        )
        return result

    finally:
        await conn.close()


@workflow.defn(name="WeeklyFairnessWorkflow")
class WeeklyFairnessWorkflow:
    """
    Cron-triggered weekly fairness audit.

    Runs every Monday at 03:00 UTC.  Computes all 9 fairness metric families
    from ml_decision_audit and prediction_feedback, writes the aggregate to
    fairness_audit_log, and surfaces flags for dashboard alerting.

    Schedule via Temporal UI / CLI:
      tctl schedule create \
        --schedule "CRON_TZ=UTC 0 3 * * 1" \
        --workflow-type WeeklyFairnessWorkflow
    """

    @workflow.run
    async def run(self) -> dict[str, Any]:
        workflow.logger.info("fairness_workflow.started")
        result = await workflow.execute_activity(
            compute_fairness_metrics_activity,
            start_to_close_timeout=timedelta(seconds=120),
            retry_policy={
                "maximum_attempts": 3,
                "initial_interval": timedelta(seconds=10),
            },
        )
        workflow.logger.info(
            "fairness_workflow.completed",
            status=result.get("overall_status"),
            flags=result.get("flags"),
        )
        return result
