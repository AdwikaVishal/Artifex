#!/usr/bin/env python3
"""
Train an XGBoost disruption-risk classifier from PostgreSQL placement history.

Outputs:
    models/risk_model.pkl        – trained XGBoost model (joblib)
    models/feature_columns.json  – ordered feature list for inference

Usage:
    python scripts/train_risk_model.py

Requirements:
    pip install xgboost scikit-learn joblib pandas
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import joblib
import pandas as pd
from dotenv import load_dotenv
from sklearn.metrics import classification_report, roc_auc_score
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://artifex:artifex123@localhost:5432/placements"
)


FEATURE_COLS = [
    "age",
    "siblings",
    "special_needs",
    "reason_Educational Neglect",
    "reason_Medical Neglect",
    "reason_Neglect",
    "reason_Other",
    "reason_Physical Abuse",
    "reason_Psychological Abuse",
    "reason_Sex Trafficking",
    "reason_Sexual Abuse",
]


def main() -> None:
    import asyncpg  # noqa: PLC0415

    async def _fetch() -> pd.DataFrame:
        print("Connecting to PostgreSQL...")
        conn = await asyncpg.connect(DATABASE_URL, timeout=5.0)
        try:
            rows = await conn.fetch(
                """
                SELECT
                    ph.child_id,
                    ph.disruption,
                    c.age,
                    c.sibling_group AS siblings,
                    c.special_needs,
                    c.intake_reason
                FROM placement_history ph
                LEFT JOIN children c ON ph.child_id = c.child_id
                """
            )
            return pd.DataFrame([dict(r) for r in rows])
        finally:
            await conn.close()

    df = asyncio.run(_fetch())

    if df.empty:
        print("ERROR: No placement history found in database.")
        return

    print(f"Loaded {len(df)} placement records from PostgreSQL.")

    # ── Feature engineering ───────────────────────────────────────────
    features = pd.DataFrame(index=df.index)

    features["age"] = df["age"].fillna(10).astype(int)
    features["siblings"] = df["siblings"].fillna(0).astype(int)
    features["special_needs"] = df["special_needs"].fillna(False).astype(int)

    # One-hot encode intake_reason
    for reason in [col.replace("reason_", "") for col in FEATURE_COLS if col.startswith("reason_")]:
        features[f"reason_{reason}"] = (df["intake_reason"].fillna("Other") == reason).astype(int)

    # Ensure all expected columns exist
    for col in FEATURE_COLS:
        if col not in features:
            features[col] = 0

    # Target
    y = df["disruption"].fillna(False).astype(int).values

    print(f"  Samples: {len(features):,}  |  Features: {features.shape[1]}  |  "
          f"Disruption rate: {y.mean()*100:.1f}%")

    X_train, X_test, y_train, y_test = train_test_split(
        features, y, test_size=0.2, random_state=42, stratify=y
    )

    print("\nTraining XGBoost classifier...")
    model = XGBClassifier(
        n_estimators=200,
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

    # ── Evaluation ────────────────────────────────────────────────────
    y_pred  = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1]
    auc     = roc_auc_score(y_test, y_proba)

    print(f"\nTest AUC-ROC: {auc:.4f}")
    print("\nClassification report:")
    print(classification_report(y_test, y_pred, target_names=["Stable", "Disrupted"]))

    # ── Save model + feature list ──────────────────────────────────────
    Path("models").mkdir(exist_ok=True)
    joblib.dump(model, "models/risk_model.pkl")

    with open("models/feature_columns.json", "w") as f:
        json.dump(FEATURE_COLS, f, indent=2)

    print(f"Model saved to models/risk_model.pkl")
    print(f"Feature columns saved to models/feature_columns.json")
    print(f"\nTop 5 feature importances:")
    importances = sorted(
        zip(FEATURE_COLS, model.feature_importances_),
        key=lambda x: x[1], reverse=True
    )
    for feat, imp in importances[:5]:
        print(f"  {feat:<45} {imp:.4f}")


if __name__ == "__main__":
    main()
