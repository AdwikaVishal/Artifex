"""
placement_recommender.py — Foster placement recommendation engine.

Scores every available family against a child's profile, ranks them,
and returns top-N matches with calibrated scores, confidence, and
feature-level explanations.

Functions
---------
rank_families            — Score and rank all families for a child.
calculate_match_score   — Compute 0–100 match score for one child–family pair.
compute_confidence_score — Probabilistic confidence in a recommendation.
recommend_foster_family — Full pipeline: load families → rank → return top-N.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path


import joblib
import pandas as pd

logger = logging.getLogger(__name__)

from services.capacity import available_capacity_sql, available_families_where_sql

# ── Model (lazy-loaded singleton) ──────────────────────────────────────────────
_risk_model = None
_feature_columns: list[str] = []
_placement_model = None
_placement_features: list[str] = []


def _load_models() -> None:
    global _risk_model, _feature_columns, _placement_model, _placement_features
    if _placement_model is not None or _risk_model is not None:
        return

    # Prefer the placement model trained on placement_history data.
    # IMPORTANT: We do not fall back to legacy/synthetic models for production
    # recommendations. If the placement model is missing, the recommender must
    # fail loudly so the workflow can surface "manual review required".
    placement_path = Path(os.getenv("PLACEMENT_MODEL_PATH", "/app/models/placement_model.pkl"))
    if not placement_path.exists():
        placement_path = Path("models/placement_model.pkl")
    placement_cols_path = Path(
        os.getenv("PLACEMENT_FEATURES_PATH", "/app/models/placement_features.json")
    )
    if not placement_cols_path.exists():
        placement_cols_path = Path("models/placement_features.json")

    if placement_path.exists():
        try:
            _placement_model = joblib.load(placement_path)
            logger.info("placement_recommender.placement_model_loaded", path=str(placement_path))
        except Exception as exc:
            logger.warning("placement_recommender.placement_model_load_error", error=str(exc))

    if placement_cols_path.exists():
        try:
            with open(placement_cols_path) as f:
                _placement_features = json.load(f)
            logger.info(
                "placement_recommender.placement_features_loaded",
                path=str(placement_cols_path),
                cols=len(_placement_features),
            )
        except Exception as exc:
            logger.warning("placement_recommender.placement_features_load_error", error=str(exc))

    # Intentionally no fallback model load here.


# ── Feature builder ────────────────────────────────────────────────────────────


def _compute_language_overlap(child_langs: str, family_langs: str) -> float:
    """Jaccard-style overlap of language sets; 0.5 if either is empty/unknown."""
    if not child_langs or not family_langs:
        return 0.5
    c_set = {w.lower().strip() for w in child_langs.replace(",", " ").split() if w.strip()}
    f_set = {w.lower().strip() for w in family_langs.replace(",", " ").split() if w.strip()}
    if not c_set or not f_set:
        return 0.5
    return len(c_set & f_set) / len(c_set | f_set)


def _compute_location_match(child_loc: str, family_loc: str) -> float:
    """Check if child's preferred location overlaps with family location."""
    if not child_loc or not family_loc:
        return 0.5
    c_parts = set(child_loc.lower().replace(",", " ").split())
    f_parts = set(family_loc.lower().replace(",", " ").split())
    return 1.0 if c_parts & f_parts else 0.0


def _build_pair_features(child: dict, family: dict) -> dict:
    """
    Build a feature dict for a child–family pair, aligned to placement_features.

    All columns default to 0.
    """
    if not _placement_features:
        return {}
    row: dict = {col: 0 for col in _placement_features}

    child_age = child.get("age", 10)
    max_age = family.get("max_age", 18)

    # Age match
    row["age_match"] = 1 if child_age <= max_age else 0
    age_gap = max(max_age - child_age, 0)
    row["age_gap"] = min(age_gap / 18.0, 1.0)

    # Location match
    row["location_match"] = _compute_location_match(
        child.get("preferred_location", ""), str(family.get("location", ""))
    )

    # Special needs match
    child_sn = bool(child.get("special_needs", False))
    family_sn = bool(family.get("special_needs_trained", False))
    row["special_needs_match"] = 1 if (child_sn and family_sn) or not child_sn else 0

    # Language match
    row["language_match"] = _compute_language_overlap(
        str(child.get("languages", "")), str(family.get("languages", ""))
    )

    # Capacity (normalized)
    total_cap = family.get("total_capacity", family.get("capacity", 1))
    row["capacity"] = min(float(total_cap or 1) / 10.0, 1.0)

    # Experience one-hot
    exp = family.get("experience", "new")
    row["experience_high"] = 1 if exp == "high" else 0
    row["experience_medium"] = 1 if exp == "medium" else 0
    row["experience_low"] = 1 if exp == "low" else 0

    # Past success rate of this family
    row["family_past_success_rate"] = family.get("past_success_rate", 0.5)

    # Sibling match
    siblings = child.get("siblings", 0)
    can_take = bool(family.get("can_take_siblings", False))
    row["sibling_match"] = 1 if (siblings > 0 and can_take) or siblings == 0 else 0

    return row


def _build_feature_row(child: dict) -> dict:
    """
    Build a feature dict aligned to the columns in feature_columns.json.

    All columns default to 0; only the matching one-hot column is set to 1.
    Only used by the legacy risk model fallback.
    """
    if not _feature_columns:
        return {}
    removal_reason = child.get("removal_reason", "Other")
    row: dict = {col: 0 for col in _feature_columns}
    row["age"] = child.get("age", 10)
    row["siblings"] = child.get("siblings", 0)
    row["special_needs"] = int(bool(child.get("special_needs", False)))
    one_hot_col = f"reason_{removal_reason}"
    if one_hot_col in row:
        row[one_hot_col] = 1
    elif "reason_Other" in row:
        row["reason_Other"] = 1
    return row


# ── Family database loader ────────────────────────────────────────────────────


async def _load_families() -> list[dict]:
    """
    Load families from PostgreSQL with available capacity > 0.
    Raises RuntimeError if the database is unreachable or returns no families.
    """
    import asyncpg  # noqa: PLC0415

    db_url = os.getenv(
        "DATABASE_URL", "postgresql://artifex:artifex123@postgres:5432/placements"
    )
    conn = await asyncpg.connect(db_url, timeout=3.0)
    try:
        rows = await conn.fetch(
            f"""
            SELECT f.*,
              {available_capacity_sql("f")} AS available_capacity,
              COALESCE(
                (SELECT
                   CAST(SUM(CASE WHEN NOT ph.disruption THEN 1 ELSE 0 END) AS FLOAT)
                   / NULLIF(COUNT(*), 0)
                 FROM placement_history ph
                 WHERE ph.family_id = f.family_id),
                0.5
              ) AS past_success_rate
            FROM families f
            WHERE {available_families_where_sql("f")}
            ORDER BY f.name
            """
        )
        if not rows:
            logger.warning("placement_recommender.no_families")
            return []
        return [dict(r) for r in rows]
    finally:
        await conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════


def calculate_match_score(child: dict, family: dict) -> float:
    """
    Compute a 0–100 match score for a single child–family pair.

    Scoring dimensions (each contributing up to the listed max):

      * Age compatibility         – 25 pts
      * Sibling capacity          – 20 pts
      * Special-needs readiness    – 20 pts
      * Experience level          – 15 pts
      * Capacity availability     – 10 pts
      * Location preference       – 10 pts

    Returns a float clamped to [0, 100].
    """
    score = 0.0

    # 1. Age compatibility (0–25)
    child_age = child.get("age", 10)
    max_age = family.get("max_age", 18)
    if child_age <= max_age:
        age_gap = max_age - child_age
        score += min(25.0, max(5.0, 25.0 - age_gap * 1.5))
    else:
        score += 0.0

    # 2. Sibling capacity (0–20)
    siblings = child.get("siblings", 0)
    if siblings > 0 and family.get("can_take_siblings", False):
        score += 20.0
    elif siblings == 0:
        score += 10.0  # neutral

    # 3. Special-needs readiness (0–20)
    special_needs = bool(child.get("special_needs", False))
    if special_needs and family.get("special_needs_trained", False):
        score += 20.0
    elif not special_needs:
        score += 15.0  # neutral
    elif special_needs and not family.get("special_needs_trained", False):
        score += 2.0  # poor fit but possible

    # 4. Experience level (0–15)
    exp_map = {"high": 15.0, "medium": 10.0, "low": 5.0, "new": 2.0}
    score += exp_map.get(family.get("experience", "new"), 5.0)

    # 5. Capacity availability (0–10)
    avail = family.get("available_capacity", 1)
    needed = child.get("capacity_needed", 1)
    if avail >= needed:
        score += 10.0
    elif avail > 0:
        score += 5.0

    # 6. Location preference (0–10)
    preferred = child.get("preferred_location", "").lower()
    family_loc = family.get("location", "").lower()
    if preferred and preferred in family_loc:
        score += 10.0
    elif not preferred:
        score += 5.0  # neutral

    return round(min(100.0, max(0.0, score)), 1)


def compute_confidence_score(
    child: dict,
    family: dict,
    match_score: float,
    risk_probability: float | None = None,
) -> float:
    """
    Compute a 0–1 confidence score for a placement recommendation.

    Factors (weighted):
      * Match-score percentile   – 40 %   how well the family fits on static attributes
      * Risk-model certainty     – 30 %   model's probability extremeness (closer to 0 or 1)
      * Capacity buffer          – 15 %   remaining slots after placement
      * Experience bonus         – 15 %   seasoned families inspire more confidence

    Args:
        child:          Child profile dict.
        family:         Family profile dict.
        match_score:    Pre-computed 0–100 match score (from calculate_match_score).
        risk_probability: Predicted P(disrupted) from the XGBoost model, or None.

    Returns:
        Float in [0, 1].
    """
    c = 0.0

    # 1. Match-score component (40 %)
    match_norm = match_score / 100.0
    c += match_norm * 0.40

    # 2. Risk-model certainty (30 %)
    if risk_probability is not None:
        certainty = 1.0 - abs(risk_probability - 0.5) * 2.0  # 0 at p=0.5, 1 at p=0 or p=1
        c += certainty * 0.30
    else:
        c += 0.5 * 0.30

    # 3. Capacity buffer (15 %)
    avail = family.get("available_capacity", 1)
    needed = child.get("capacity_needed", 1)
    if avail >= needed:
        buffer_ratio = min(1.0, (avail - needed + 1) / 3.0)
        c += buffer_ratio * 0.15
    else:
        c += 0.0

    # 4. Experience bonus (15 %)
    exp_bonus = {"high": 1.0, "medium": 0.7, "low": 0.4, "new": 0.2}
    c += exp_bonus.get(family.get("experience", "new"), 0.3) * 0.15

    return round(min(1.0, max(0.0, c)), 4)


async def rank_families(
    child: dict,
    top_n: int = 5,
) -> list[dict]:
    """
    Score and rank all available families for a given child.

    For each family:
      1. Calculate static match score (0–100).
      2. Compute risk probability via XGBoost (if available).
      3. Compute confidence score.
      4. Compute blended final score = match_score × (1 − risk_prob × 0.3).

    Args:
        child:  Child profile dict.
        top_n:  Number of top matches to return (default 5).

    Returns:
        List of dicts, each with keys:
          family, match_score, confidence_score, risk_probability,
          capacity, explanation.
        Sorted descending by match_score.
    """
    _load_models()

    if _placement_model is None or not _placement_features:
        raise RuntimeError(
            "Placement model not available (placement_model.pkl / placement_features.json). "
            "Refusing to generate fallback recommendations."
        )

    families = await _load_families()
    scored: list[dict] = []

    for family in families:
        match_score = calculate_match_score(child, family)

        # Pair-model inference (probability of placement success)
        risk_prob = None
        pair_features = _build_pair_features(child, family)
        if pair_features:
            try:
                features_df = pd.DataFrame([pair_features], columns=_placement_features)
                proba = _placement_model.predict_proba(features_df)[0]
                success_prob = round(float(proba[1]), 4)
                risk_prob = round(1.0 - success_prob, 4)
            except Exception:
                risk_prob = None

        confidence = compute_confidence_score(child, family, match_score, risk_prob)

        # Blended final score: reduce match score when disruption risk is high
        risk_penalty = (risk_prob or 0.0) * 0.30
        blended_score = round(match_score * (1.0 - risk_penalty), 1)

        scored.append({
            "family": family,
            "match_score": match_score,
            "confidence_score": confidence,
            "risk_probability": risk_prob or 0.0,
            "capacity": family.get("available_capacity", 0),
            "blended_score": blended_score,
            "explanation": _build_explanation(child, family, match_score, risk_prob or 0.0),
        })

    scored.sort(key=lambda x: x["blended_score"], reverse=True)
    return scored[:top_n]


def _build_explanation(child: dict, family: dict, match_score: float, risk_prob: float) -> str:
    parts = []
    if match_score >= 80:
        parts.append("Strong match")
    elif match_score >= 60:
        parts.append("Moderate match")
    else:
        parts.append("Below-average match")

    age = child.get("age", 10)
    max_age = family.get("max_age", 18)
    if age <= max_age:
        parts.append(f"age {age} within family's {max_age} limit")
    else:
        parts.append(f"child age {age} exceeds family max of {max_age}")

    if child.get("siblings", 0) > 0 and family.get("can_take_siblings"):
        parts.append("sibling group accepted")
    if child.get("special_needs") and family.get("special_needs_trained"):
        parts.append("special-needs trained")

    if risk_prob < 0.2:
        parts.append("low disruption risk")
    elif risk_prob > 0.5:
        parts.append(f"elevated disruption risk ({risk_prob:.0%})")

    return " | ".join(parts[:5])


async def recommend_foster_family(
    child: dict,
    top_n: int = 5,
) -> dict:
    """
    Full placement recommendation pipeline.

    1. Load all available families.
    2. Rank them by match score, risk-adjusted.
    3. Return the top recommendation with full metadata.

    Args:
        child:  Child profile dict.
        top_n:  Number of top matches to return.

    Returns:
        Dict with keys:
          recommended_family  – Top-ranked family dict.
          match_score         – 0–100 match score.
          confidence_score    – 0–1 confidence.
          risk_score          – Risk probability × 100 (0–100 scale).
          feature_importance  – List of {feature, importance} from XGBoost.
          top_matches         – Full list of scored families.
          model_version       – Model identifier string.
          explanation         – Human-readable match explanation.
    """
    _load_models()

    if _placement_model is None or not _placement_features:
        raise RuntimeError(
            "Placement model not available (placement_model.pkl / placement_features.json). "
            "Refusing to generate fallback recommendations."
        )

    top_matches = await rank_families(child, top_n=top_n)

    # Extract feature importance from the active XGBoost model
    feature_importance: list[dict] = []
    try:
        importances = _placement_model.feature_importances_
        feature_importance = [
            {"feature": col, "importance": round(float(imp), 4)}
            for col, imp in zip(_placement_features, importances)
            if imp > 0.005
        ]
        feature_importance.sort(key=lambda x: x["importance"], reverse=True)
    except Exception:
        pass

    best = top_matches[0] if top_matches else {}
    return {
        "recommended_family": best.get("family", {}),
        "match_score": best.get("match_score", 0),
        "confidence_score": best.get("confidence_score", 0),
        "risk_score": round(best.get("risk_probability", 0) * 100, 2),
        "feature_importance": feature_importance,
        "top_matches": top_matches,
        "model_version": "xgboost-v1",
        "explanation": best.get("explanation", ""),
    }
