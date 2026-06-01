"""
api/services/crisis_predictor.py – Predictive Crisis Engine.

Predicts placement disruption risk in the next 21 days and recommends
interventions. Uses XGBoost if a trained model is available, otherwise
falls back to a transparent rule-based predictor.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()
_process_logger = logging.getLogger("artifex.crisis_predictor")


class CrisisPredictor:
    """Predicts 21-day placement disruption risk for a given placement."""

    def __init__(self) -> None:
        self.model: Any = None
        self.model_type: str = "rule_based"
        self._load_model()

    def _load_model(self) -> None:
        """Load XGBoost model if available; fall back to rule-based."""
        model_path = Path(
            os.getenv("CRISIS_MODEL_PATH", "/app/models/crisis_model.pkl")
        )
        if not model_path.exists():
            model_path = Path("models/crisis_model.pkl")

        if model_path.exists():
            try:
                import joblib  # noqa: PLC0415
                self.model = joblib.load(model_path)
                self.model_type = "ml"
                _process_logger.info(
                    "crisis_predictor.model_loaded", path=str(model_path)
                )
            except Exception as exc:  # noqa: BLE001
                _process_logger.warning(
                    "crisis_predictor.model_load_error",
                    error=str(exc),
                )
                self.model_type = "rule_based"
        else:
            _process_logger.info(
                "crisis_predictor.using_rule_based",
                note="No crisis_model.pkl found – rule-based fallback active",
            )

    async def get_placement_features(
        self, placement_id: str
    ) -> dict[str, Any] | None:
        """Collect features from existing DB tables for a given placement."""
        from api.db import get_pool  # noqa: PLC0415

        pool = get_pool()
        if pool is None:
            return None

        async with pool.acquire() as conn:
            # Placement row
            placement = await conn.fetchrow(
                "SELECT * FROM placements WHERE workflow_id = $1", placement_id
            )
            if not placement:
                return None

            child_id = placement["child_id"]

            # Child attributes
            child = await conn.fetchrow(
                "SELECT * FROM children WHERE child_id = $1", child_id
            )
            if not child:
                return None

            # Recent check-ins (last 30 days) – use check_ins table schema
            # check_ins has: child_id, placement_id, mood_score, incident_reported, notes, timestamp
            incident_row = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) AS count,
                    AVG(mood_score) AS avg_mood
                FROM check_ins
                WHERE child_id = $1
                  AND timestamp > NOW() - INTERVAL '30 days'
                """,
                child_id,
            )

            # Risk score history from placement_predictions
            risk_rows = await conn.fetch(
                """
                SELECT risk_score
                FROM placement_predictions
                WHERE workflow_id = $1
                ORDER BY created_at DESC
                LIMIT 5
                """,
                placement_id,
            )
            risk_scores = [
                float(r["risk_score"])
                for r in risk_rows
                if r["risk_score"] is not None
            ]
            risk_trend = (
                risk_scores[0] - risk_scores[-1] if len(risk_scores) > 1 else 0.0
            )

            # Disruption rate for similar-age children
            child_age = child["age"] or 10
            similar_row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS disruptions
                FROM placement_history ph
                JOIN children c ON c.child_id = ph.child_id
                WHERE c.age BETWEEN $1 AND $2
                  AND c.special_needs = $3
                  AND ph.disruption = TRUE
                """,
                max(0, child_age - 2),
                child_age + 2,
                bool(child.get("special_needs", False)),
            )

            # Days in current placement
            placement_created = placement.get("created_at")
            days_in_placement = (
                (datetime.now() - placement_created.replace(tzinfo=None)).days
                if placement_created
                else 30
            )

            incident_count = int(incident_row["count"]) if incident_row else 0
            avg_mood = float(incident_row["avg_mood"] or 3.0) if incident_row else 3.0
            disruptions = int(similar_row["disruptions"]) if similar_row else 0

            return {
                "placement_id": placement_id,
                "child_id": child_id,
                "risk_score": float(placement.get("risk_score") or 0.0),
                "risk_trend": risk_trend,
                "incident_count_30d": incident_count,
                # Invert mood: low mood → higher severity proxy
                "incident_severity": max(0.0, (5.0 - avg_mood) / 4.0 * 3.0),
                "age": child_age,
                "special_needs": 1 if child.get("special_needs") else 0,
                "siblings": child.get("sibling_count", 0) or 0,
                "disruption_rate_similar": disruptions / max(disruptions + 10, 1),
                "time_in_placement_days": days_in_placement,
            }

    def _predict_rule_based(
        self, features: dict[str, Any]
    ) -> dict[str, Any]:
        """Transparent rule-based predictor (fallback when no ML model)."""
        probability = features["risk_score"] * 0.6
        probability += features["incident_count_30d"] * 8.0
        probability += features["risk_trend"] * 2.0
        # Low mood proxy
        probability += features["incident_severity"] * 5.0
        # Very new placements are higher risk
        if features["time_in_placement_days"] < 14:
            probability += 10.0
        probability = min(max(probability, 0.0), 100.0)

        reasons: list[dict[str, Any]] = []
        if features["risk_score"] > 70:
            reasons.append(
                {"reason": "Current risk score is high", "weight": 35}
            )
        if features["incident_count_30d"] > 2:
            reasons.append(
                {
                    "reason": f"{features['incident_count_30d']} incidents in last 30 days",
                    "weight": 30,
                }
            )
        if features["risk_trend"] > 10:
            reasons.append(
                {"reason": "Risk score is increasing rapidly", "weight": 20}
            )
        if features["special_needs"] and features["incident_severity"] > 1.5:
            reasons.append(
                {
                    "reason": "Special needs child with low mood scores",
                    "weight": 15,
                }
            )
        if features["time_in_placement_days"] < 14:
            reasons.append(
                {"reason": "Placement is less than 2 weeks old", "weight": 10}
            )
        if features["disruption_rate_similar"] > 0.3:
            reasons.append(
                {
                    "reason": "High disruption rate for similar children",
                    "weight": 10,
                }
            )

        interventions: list[str] = []
        if probability > 60:
            interventions.append("Schedule therapy review")
        if features["incident_count_30d"] > 1:
            interventions.append("Assign mentor support")
        if features["risk_trend"] > 5:
            interventions.append("Increase caseworker check-in frequency")
        if features["special_needs"]:
            interventions.append("Verify special-needs support plan is current")
        if not interventions:
            interventions.append("Continue standard monitoring")

        return {
            "probability": round(probability, 1),
            "risk_level": (
                "critical"
                if probability > 80
                else "high"
                if probability > 60
                else "medium"
                if probability > 30
                else "low"
            ),
            "top_reasons": reasons[:4],
            "recommended_interventions": interventions[:3],
        }

    def _predict_ml(self, features: dict[str, Any]) -> dict[str, Any]:
        """Use XGBoost model for prediction."""
        try:
            import pandas as pd  # noqa: PLC0415

            feature_df = pd.DataFrame(
                [
                    {
                        "risk_score": features["risk_score"],
                        "risk_trend": features["risk_trend"],
                        "incident_count": features["incident_count_30d"],
                        "incident_severity": features["incident_severity"],
                        "age": features["age"],
                        "special_needs": features["special_needs"],
                        "siblings": features["siblings"],
                        "disruption_rate": features["disruption_rate_similar"],
                        "time_in_placement": features["time_in_placement_days"],
                    }
                ]
            )
            probability = float(
                self.model.predict_proba(feature_df)[0][1] * 100
            )
        except Exception as exc:  # noqa: BLE001
            _process_logger.warning(
                "crisis_predictor.ml_predict_error",
                error=str(exc),
                fallback="rule_based",
            )
            return self._predict_rule_based(features)

        # Build reasons from feature values (SHAP-lite)
        reasons: list[dict[str, Any]] = []
        if features["risk_score"] > 70:
            reasons.append({"reason": "Current risk score is high", "weight": 35})
        if features["incident_count_30d"] > 2:
            reasons.append(
                {
                    "reason": f"{features['incident_count_30d']} incidents in last 30 days",
                    "weight": 30,
                }
            )
        if features["risk_trend"] > 10:
            reasons.append(
                {"reason": "Risk score is increasing rapidly", "weight": 20}
            )

        interventions = ["Therapy review", "Increased monitoring"]
        if features["incident_count_30d"] > 1:
            interventions.append("Assign mentor support")

        return {
            "probability": round(probability, 1),
            "risk_level": (
                "critical"
                if probability > 80
                else "high"
                if probability > 60
                else "medium"
                if probability > 30
                else "low"
            ),
            "top_reasons": reasons[:4],
            "recommended_interventions": interventions[:3],
        }

    async def predict_and_store(
        self, placement_id: str
    ) -> dict[str, Any] | None:
        """Generate a prediction and persist it to crisis_predictions."""
        from api.db import get_pool  # noqa: PLC0415

        features = await self.get_placement_features(placement_id)
        if not features:
            return None

        if self.model_type == "ml":
            prediction = self._predict_ml(features)
        else:
            prediction = self._predict_rule_based(features)

        pool = get_pool()
        if pool is not None:
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO crisis_predictions
                            (placement_id, child_id, disruption_probability,
                             risk_level, top_reasons, recommended_interventions,
                             model_version)
                        VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7)
                        """,
                        placement_id,
                        features["child_id"],
                        prediction["probability"],
                        prediction["risk_level"],
                        json.dumps(prediction["top_reasons"]),
                        json.dumps(prediction["recommended_interventions"]),
                        self.model_type,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "crisis_predictor.store_error",
                    placement_id=placement_id,
                    error=str(exc),
                )

        return prediction


# ── Singleton ─────────────────────────────────────────────────────────────────

_crisis_predictor: CrisisPredictor | None = None


def get_crisis_predictor() -> CrisisPredictor:
    global _crisis_predictor
    if _crisis_predictor is None:
        _crisis_predictor = CrisisPredictor()
    return _crisis_predictor
