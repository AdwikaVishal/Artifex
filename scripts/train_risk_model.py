#!/usr/bin/env python3
"""
Train an XGBoost disruption-risk classifier on the synthetic AFCARS data.

Outputs:
    models/risk_model.pkl        – trained XGBoost model (joblib)
    models/feature_columns.json  – ordered feature list for inference

Usage:
    python scripts/train_risk_model.py

Requirements:
    pip install xgboost scikit-learn joblib pandas
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import pandas as pd
from sklearn.metrics import classification_report, roc_auc_score
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier


def main() -> None:
    features_path = Path("data/features.csv")
    labels_path   = Path("data/labels.csv")

    if not features_path.exists() or not labels_path.exists():
        print("ERROR: training data not found.")
        print("Run: python scripts/generate_training_data.py")
        return

    print("Loading training data...")
    X = pd.read_csv(features_path)
    y = pd.read_csv(labels_path).values.ravel()

    print(f"  Samples: {len(X):,}  |  Features: {X.shape[1]}  |  "
          f"Disruption rate: {y.mean()*100:.1f}%")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    print("\nTraining XGBoost classifier...")
    model = XGBClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        scale_pos_weight=(y == 0).sum() / (y == 1).sum(),  # handle imbalance
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

    feature_cols = list(X.columns)
    with open("models/feature_columns.json", "w") as f:
        json.dump(feature_cols, f, indent=2)

    print(f"Model saved to models/risk_model.pkl")
    print(f"Feature columns saved to models/feature_columns.json")
    print(f"\nTop 5 feature importances:")
    importances = sorted(
        zip(feature_cols, model.feature_importances_),
        key=lambda x: x[1], reverse=True
    )
    for feat, imp in importances[:5]:
        print(f"  {feat:<45} {imp:.4f}")


if __name__ == "__main__":
    main()
