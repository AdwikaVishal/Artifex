#!/usr/bin/env python3
"""
Generate synthetic foster child profiles based on real AFCARS distributions.

Reads the FY 2024 Title IV-E Foster Care Claims and Caseload Excel file
(fy2024-iv-e-foster-care-claims-caseload.xlsx) for the national caseload
total, then generates that many synthetic child profiles using AFCARS
age-at-entry, removal reason, sibling group, and special needs distributions.

Usage:
    python scripts/generate_synthetic_foster_children.py
    python scripts/generate_synthetic_foster_children.py --count 500
    python scripts/generate_synthetic_foster_children.py --state California

Output:
    data/synthetic_foster_children.json
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import structlog

logger = structlog.get_logger()

# ── Excel file (project root) ─────────────────────────────────────────────────
EXCEL_FILE = Path("fy2024-iv-e-foster-care-claims-caseload.xlsx")
SHEET_NAME = "FY 2024 IV-E FC"
# Column index (0-based) for "Total Title IV-E FCMP Caseload" = column 27
CASELOAD_COL = 27
# Row index (0-based) where state data begins
STATE_DATA_START_ROW = 8


def get_caseload_from_excel(state: str | None = None) -> int:
    """
    Read the national (or state-level) average monthly caseload from the
    FY 2024 Title IV-E Excel file.

    Returns an integer count; falls back to 112_322 (FY2024 national total)
    if the file cannot be read.
    """
    if not EXCEL_FILE.exists():
        logger.warning(
            "excel_not_found",
            path=str(EXCEL_FILE),
            fallback=112_322,
        )
        return 112_322

    try:
        import openpyxl  # noqa: PLC0415

        wb = openpyxl.load_workbook(EXCEL_FILE, read_only=True, data_only=True)
        ws = wb[SHEET_NAME]
        rows = list(ws.iter_rows(values_only=True))

        if state:
            # Find the row matching the requested state name
            for row in rows[STATE_DATA_START_ROW:]:
                if row[0] and state.lower() in str(row[0]).lower():
                    val = row[CASELOAD_COL]
                    if val is not None:
                        count = int(round(float(val)))
                        logger.info("excel_caseload_state", state=row[0], count=count)
                        return count
            logger.warning("excel_state_not_found", state=state, fallback=112_322)
            return 112_322

        # National Total row
        for row in rows:
            if row[0] and "national total" in str(row[0]).lower():
                val = row[CASELOAD_COL]
                if val is not None:
                    count = int(round(float(val)))
                    logger.info("excel_caseload_national", count=count)
                    return count

    except Exception as exc:  # noqa: BLE001
        logger.warning("excel_read_error", error=str(exc), fallback=112_322)

    return 112_322


# ── AFCARS distributions ──────────────────────────────────────────────────────

# Age at entry (AFCARS Entries dashboard, FY 2023 national)
AGE_DISTRIBUTION: dict[str, float] = {
    "<1":    0.182,
    "1-5":   0.268,
    "6-10":  0.210,
    "11-16": 0.276,
    "17":    0.038,
    "18-23": 0.026,
}

# Removal reasons (exact AFCARS counts, normalised)
_REMOVAL_COUNTS: dict[str, int] = {
    "Neglect":              95_790,
    "Physical Abuse":       22_996,
    "Sexual Abuse":          7_053,
    "Psychological Abuse":   6_681,
    "Medical Neglect":       4_559,
    "Educational Neglect":   7_326,
    "Sex Trafficking":         523,
    "Other":                29_080,
}
_REMOVAL_TOTAL = sum(_REMOVAL_COUNTS.values())
REMOVAL_DISTRIBUTION: dict[str, float] = {
    k: v / _REMOVAL_TOTAL for k, v in _REMOVAL_COUNTS.items()
}

# Sibling groups (state-agency estimates; not directly in AFCARS)
SIBLING_DISTRIBUTION: dict[int, float] = {
    0: 0.60,
    1: 0.25,
    2: 0.10,
    3: 0.05,   # 3 or more
}

# Special needs (AFCARS-adjacent estimates)
SPECIAL_NEEDS_DISTRIBUTION: dict[bool, float] = {
    True:  0.35,
    False: 0.65,
}


def _age_from_group(group: str) -> int:
    mapping = {
        "<1":    (0, 0),
        "1-5":   (1, 5),
        "6-10":  (6, 10),
        "11-16": (11, 16),
        "17":    (17, 17),
        "18-23": (18, 23),
    }
    lo, hi = mapping[group]
    return random.randint(lo, hi)


def generate_children(count: int) -> list[dict]:
    """Generate `count` synthetic child profiles."""
    age_groups   = list(AGE_DISTRIBUTION.keys())
    age_weights  = list(AGE_DISTRIBUTION.values())
    rem_reasons  = list(REMOVAL_DISTRIBUTION.keys())
    rem_weights  = list(REMOVAL_DISTRIBUTION.values())
    sib_counts   = list(SIBLING_DISTRIBUTION.keys())
    sib_weights  = list(SIBLING_DISTRIBUTION.values())
    sn_values    = list(SPECIAL_NEEDS_DISTRIBUTION.keys())
    sn_weights   = list(SPECIAL_NEEDS_DISTRIBUTION.values())

    children = []
    for i in range(count):
        age_group      = random.choices(age_groups,  weights=age_weights)[0]
        removal_reason = random.choices(rem_reasons, weights=rem_weights)[0]
        siblings       = random.choices(sib_counts,  weights=sib_weights)[0]
        special_needs  = random.choices(sn_values,   weights=sn_weights)[0]

        children.append({
            "child_id":       f"SYN-{i:06d}",
            "age":            _age_from_group(age_group),
            "age_group":      age_group,
            "removal_reason": removal_reason,
            "siblings":       siblings,
            "special_needs":  special_needs,
        })
    return children


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate synthetic foster child profiles from AFCARS distributions"
    )
    parser.add_argument(
        "--count", type=int, default=None,
        help="Override number of children to generate (default: read from Excel)",
    )
    parser.add_argument(
        "--state", type=str, default=None,
        help="Generate only for a specific state (e.g. 'California')",
    )
    parser.add_argument(
        "--output", type=str, default="data/synthetic_foster_children.json",
        help="Output JSON file path",
    )
    args = parser.parse_args()

    total = args.count or get_caseload_from_excel(state=args.state)
    print(f"Generating {total:,} synthetic child profiles"
          + (f" for {args.state}" if args.state else " (national)") + "...")

    children = generate_children(total)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(children, f, indent=2)

    # Print distribution summary
    from collections import Counter  # noqa: PLC0415
    age_counts = Counter(c["age_group"] for c in children)
    rem_counts = Counter(c["removal_reason"] for c in children)
    sn_count   = sum(1 for c in children if c["special_needs"])

    print(f"\nSaved {len(children):,} profiles to {output_path}")
    print("\nAge distribution:")
    for grp in AGE_DISTRIBUTION:
        print(f"  {grp:>6}: {age_counts[grp]:>7,}  ({age_counts[grp]/total*100:.1f}%)")
    print("\nTop removal reasons:")
    for reason, cnt in rem_counts.most_common(5):
        print(f"  {reason:<25}: {cnt:>7,}  ({cnt/total*100:.1f}%)")
    print(f"\nSpecial needs: {sn_count:,} ({sn_count/total*100:.1f}%)")


if __name__ == "__main__":
    main()
