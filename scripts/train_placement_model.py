"""
train_placement_model.py — Train XGBoost on real placement_history data.

Features are child–family pair match-quality metrics engineered from the
placement_history, children, and families tables in PostgreSQL.

Target: successful_placement (1 = NOT disrupted, 0 = disrupted)
Output: models/placement_model.pkl + models/placement_features.json

Usage:
    python scripts/train_placement_model.py

Requires PostgreSQL to be running with seeded data (run seed_families.py
and seed_placement_history.py first).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sklearn.metrics import classification_report, roc_auc_score, roc_curve
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://artifex:artifex123@localhost:5432/placements"
)


def _compute_language_overlap(child_langs: str, family_langs: str) -> float:
    """Jaccard-style overlap of language sets; 0 if either is empty/unknown."""
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
    c = child_loc.lower().strip()
    f = family_loc.lower().strip()
    # Check city-level overlap
    c_parts = set(c.replace(",", " ").split())
    f_parts = set(f.replace(",", " ").split())
    common = c_parts & f_parts
    if common:
        return 1.0
    return 0.0 if c and f else 0.5


def main() -> None:
    import asyncio

    import asyncpg  # noqa: PLC0415

    async def _fetch() -> pd.DataFrame:
        print("Connecting to PostgreSQL...")
        conn = await asyncpg.connect(DATABASE_URL, timeout=5.0)
        try:
            rows = await conn.fetch(
                """
                SELECT
                    ph.child_id,
                    ph.family_id,
                    ph.placement_start,
                    ph.placement_end,
                    ph.disruption,
                    ph.outcome,
                    c.age AS child_age,
                    c.special_needs,
                    c.sibling_group,
                    c.location AS child_location,
                    c.languages AS child_languages,
                    c.intake_reason,
                    f.max_age,
                    f.special_needs_trained,
                    f.accepts_siblings,
                    f.capacity,
                    f.experience,
                    f.location AS family_location,
                    f.languages AS family_languages,
                    f.can_take_siblings
                FROM placement_history ph
                LEFT JOIN children c ON ph.child_id = c.child_id
                LEFT JOIN families f ON ph.family_id = f.family_id
                """
            )
            return pd.DataFrame([dict(r) for r in rows])
        finally:
            await conn.close()

    df = asyncio.run(_fetch())

    if df.empty:
        print("ERROR: No placement history found. Run seed_placement_history.py first.")
        return

    print(f"Loaded {len(df)} placement records with {len(df.columns)} columns.")

    # ── Compute per-family past success rate (before splitting) ────────────
    family_stats = df.groupby("family_id").agg(
        total_placements=("disruption", "count"),
        successful_placements=("disruption", lambda x: (~x.astype(bool)).sum()),
    )
    family_stats["past_success_rate"] = (
        family_stats["successful_placements"] / family_stats["total_placements"]
    )
    df = df.merge(family_stats[["past_success_rate"]], on="family_id", how="left")

    # ── Feature engineering ────────────────────────────────────────────────
    features = pd.DataFrame(index=df.index)

    child_age = df["child_age"].fillna(10)
    max_age = df["max_age"].fillna(18)

    # Age match
    features["age_match"] = (child_age <= max_age).astype(int)
    age_gap = (max_age - child_age).clip(lower=0, upper=18)
    features["age_gap"] = (age_gap / 18.0).astype(float)

    # Location match
    features["location_match"] = [
        _compute_location_match(cl, fl)
        for cl, fl in zip(
            df["child_location"].fillna(""), df["family_location"].fillna("")
        )
    ]

    # Special needs match
    sn = df["special_needs"].fillna(False)
    sn_trained = df["special_needs_trained"].fillna(False)
    features["special_needs_match"] = (
        (sn & sn_trained) | (~sn)
    ).astype(int)

    # Language match
    features["language_match"] = [
        _compute_language_overlap(cl, fl)
        for cl, fl in zip(df["child_languages"].fillna(""), df["family_languages"].fillna(""))
    ]

    # Capacity (normalized)
    features["capacity"] = df["capacity"].fillna(1).astype(float) / 10.0

    # Experience one-hot
    features["experience_high"] = (df["experience"].fillna("new") == "high").astype(int)
    features["experience_medium"] = (df["experience"].fillna("new") == "medium").astype(int)
    features["experience_low"] = (df["experience"].fillna("new") == "low").astype(int)

    # Past success rate of this family
    features["family_past_success_rate"] = df["past_success_rate"].fillna(0.5).astype(float)

    # Sibling match
    sib = df["sibling_group"].fillna(False)
    can_sib = df["can_take_siblings"].fillna(False)
    features["sibling_match"] = (
        (sib & can_sib) | (~sib)
    ).astype(int)

    feature_cols = list(features.columns)

    # ── Target: successful_placement (1 = success, 0 = disruption) ────────
    y = (~df["disruption"].astype(bool)).astype(int)
    success_rate = y.mean()
    print(f"  Features: {len(feature_cols)}")
    print(f"  Samples:  {len(df)}")
    print(f"  Success rate: {success_rate * 100:.1f}%")

    # ── Train/Test split ───────────────────────────────────────────────────
    X_train, X_test, y_train, y_test = train_test_split(
        features, y, test_size=0.2, random_state=42, stratify=y,
    )
    print(f"\n  Training set:   {len(X_train)}")
    print(f"  Test set:       {len(X_test)}")

    # ── Train XGBoost ─────────────────────────────────────────────────────
    print("\nTraining XGBoost classifier (target = successful_placement)...")
    model = XGBClassifier(
        n_estimators=300,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        scale_pos_weight=(y == 0).sum() / (y == 1).sum(),
        eval_metric="logloss",
        random_state=42,
        verbosity=0,
    )
    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        verbose=False,
    )

    # ── Evaluation ─────────────────────────────────────────────────────────
    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1]
    auc = roc_auc_score(y_test, y_proba)

    print(f"\n{'=' * 60}")
    print(f"Test AUC-ROC: {auc:.4f}")
    print(f"{'=' * 60}")
    print("\nClassification report (target = successful_placement):")
    print(classification_report(y_test, y_pred, target_names=["Disrupted", "Successful"]))

    # Find optimal threshold
    fpr, tpr, thresholds = roc_curve(y_test, y_proba)
    youden_idx = (tpr - fpr).argmax()
    best_threshold = thresholds[youden_idx]
    print(f"\nOptimal decision threshold (Youden): {best_threshold:.3f}")

    # ── Feature importance ─────────────────────────────────────────────────
    importances = sorted(
        zip(feature_cols, model.feature_importances_),
        key=lambda x: x[1],
        reverse=True,
    )
    print("\nFeature importances:")
    for feat, imp in importances:
        print(f"  {feat:<32} {imp:.4f}")

    # ── Save model + feature columns ───────────────────────────────────────
    models_dir = Path("models")
    models_dir.mkdir(exist_ok=True)

    joblib_path = models_dir / "placement_model.pkl"
    import joblib
    joblib.dump(model, joblib_path)

    cols_path = models_dir / "placement_features.json"
    with open(cols_path, "w") as f:
        json.dump(feature_cols, f, indent=2)

    print(f"\nModel saved to {joblib_path}")
    print(f"Feature columns saved to {cols_path}")
    print("Done.")


if __name__ == "__main__":
    main()
