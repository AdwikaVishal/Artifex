#!/usr/bin/env python3
"""
Generate synthetic XGBoost training data from the AFCARS-based child profiles.

Simulates disruption outcomes using evidence-based risk factors:
  - Age at entry (older children have higher disruption rates)
  - Special needs (increases risk without trained family)
  - Sibling group size
  - Removal reason severity
  - Random noise to reflect real-world variability

Output:
    data/features.csv  – one-hot encoded feature matrix
    data/labels.csv    – binary disruption outcome (0=stable, 1=disrupted)

Usage:
    python scripts/generate_training_data.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

REMOVAL_SEVERITY: dict[str, float] = {
    "Neglect":              0.10,
    "Physical Abuse":       0.20,
    "Sexual Abuse":         0.25,
    "Psychological Abuse":  0.18,
    "Medical Neglect":      0.12,
    "Educational Neglect":  0.08,
    "Sex Trafficking":      0.30,
    "Other":                0.05,
}


def simulate_disruption(child: dict, rng: np.random.Generator) -> int:
    """
    Simulate a binary disruption outcome using evidence-based weights.
    Returns 1 (disrupted) or 0 (stable).
    """
    risk = 0.0

    # Age: teens have significantly higher disruption rates
    age = child.get("age", 10)
    if age >= 15:
        risk += 0.35
    elif age >= 11:
        risk += 0.20
    elif age >= 6:
        risk += 0.08

    # Special needs without trained placement
    if child.get("special_needs"):
        risk += 0.20

    # Sibling group complexity
    siblings = child.get("siblings", 0)
    risk += siblings * 0.06

    # Removal reason severity
    reason = child.get("removal_reason", "Other")
    risk += REMOVAL_SEVERITY.get(reason, 0.05)

    # Gaussian noise (σ=0.12) to reflect real-world variability
    risk += rng.normal(0, 0.12)

    return int(risk > 0.45)


def main() -> None:
    json_path = Path("data/synthetic_foster_children.json")
    if not json_path.exists():
        print("ERROR: data/synthetic_foster_children.json not found.")
        print("Run: python scripts/generate_synthetic_foster_children.py")
        return

    print(f"Loading children from {json_path}...")
    with open(json_path, encoding="utf-8") as f:
        children = json.load(f)

    rng = np.random.default_rng(seed=42)   # reproducible

    print(f"Simulating disruption outcomes for {len(children):,} children...")
    for child in children:
        child["disrupted"] = simulate_disruption(child, rng)

    df = pd.DataFrame(children)

    # ── Feature engineering ───────────────────────────────────────────
    features = df[["age", "siblings", "special_needs", "removal_reason"]].copy()
    features["special_needs"] = features["special_needs"].astype(int)
    features = pd.get_dummies(features, columns=["removal_reason"], prefix="reason")

    labels = df["disrupted"]

    # ── Save ──────────────────────────────────────────────────────────
    Path("data").mkdir(exist_ok=True)
    features.to_csv("data/features.csv", index=False)
    labels.to_csv("data/labels.csv", index=False)

    disruption_rate = labels.mean() * 100
    print(f"\nSaved {len(features):,} rows to data/features.csv")
    print(f"Disruption rate: {disruption_rate:.1f}%")
    print(f"Feature columns ({len(features.columns)}): {list(features.columns)}")


if __name__ == "__main__":
    main()
