#!/usr/bin/env python3
"""
Generate realistic placement history for ML training.

Creates historical placement records with:
- Realistic dates spanning 3+ years
- Mix of successful and disrupted placements (10% disruption rate)
- Varied placement durations (30 days to 5+ years)
- Realistic disruption reasons
- Child and family matching

Usage:
    python scripts/generate_placement_history.py
    python scripts/generate_placement_history.py --count 500

Output:
    Directly inserted into placement_history table
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
from datetime import date, timedelta
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://artifex:artifex123@localhost:5432/placements"
)

# Disruption reasons (national data)
DISRUPTION_REASONS = [
    "Family requested removal",
    "Child behavioral issues",
    "Family unable to meet needs",
    "Allegation of abuse/neglect",
    "Family relocation",
    "Therapeutic needs exceeded family capacity",
    "Child safety concern",
    "Family stress and overwhelm",
    "Placement incompatibility",
    "Emergency removal",
]

# Successful outcome reasons
SUCCESSFUL_OUTCOMES = [
    "Reunification",
    "Guardianship",
    "Adoption",
    "Emancipation at age 18",
    "Permanent placement - long term",
]


async def fetch_children_and_families(pool: asyncpg.Pool) -> tuple[list, list]:
    """Fetch existing children and families from database."""
    async with pool.acquire() as conn:
        children = await conn.fetch("SELECT child_id, age FROM children LIMIT 500")
        families = await conn.fetch("SELECT family_id FROM families LIMIT 100")

    return children, families


async def generate_placement_history(
    pool: asyncpg.Pool,
    children: list,
    families: list,
    count: int = 300,
) -> None:
    """Generate and insert placement history records."""
    if not children or not families:
        logger.error("No children or families found in database")
        return

    placements = []
    today = date.today()
    three_years_ago = today - timedelta(days=365 * 3)

    for _ in range(count):
        # Random child and family
        child = random.choice(children)
        family = random.choice(families)

        # Random placement start date in past 3 years
        days_back = random.randint(0, 365 * 3)
        placement_start = today - timedelta(days=days_back)

        # Duration: 30 days to 5 years, with realistic distribution
        # Most placements: 6 months - 2 years
        duration_type = random.choices(
            ["short", "medium", "long"],
            weights=[0.15, 0.65, 0.20],
            k=1,
        )[0]

        if duration_type == "short":
            duration_days = random.randint(30, 90)
        elif duration_type == "medium":
            duration_days = random.randint(90, 730)  # 3 months - 2 years
        else:
            duration_days = random.randint(730, 1825)  # 2-5 years

        placement_end = placement_start + timedelta(days=duration_days)

        # Only include placements that have ended
        if placement_end > today:
            placement_end = today - timedelta(days=random.randint(1, 30))
            duration_days = (placement_end - placement_start).days

        # Disruption: ~10% national average
        is_disrupted = random.random() < 0.10

        if is_disrupted:
            outcome = "Disrupted"
            disruption_reason = random.choice(DISRUPTION_REASONS)
        else:
            outcome = random.choice(SUCCESSFUL_OUTCOMES)
            disruption_reason = None

        placements.append({
            "child_id": child["child_id"],
            "family_id": family["family_id"],
            "placement_start": placement_start,
            "placement_end": placement_end,
            "outcome": outcome,
            "disruption": is_disrupted,
            "disruption_reason": disruption_reason,
            "duration_days": duration_days,
            "child_age_at_start": max(0, child["age"] - (duration_days // 365)),
        })

    # Insert into database
    async with pool.acquire() as conn:
        async with conn.transaction():
            for p in placements:
                await conn.execute(
                    """
                    INSERT INTO placement_history 
                    (child_id, family_id, placement_start, placement_end, 
                     outcome, disruption, disruption_reason, duration_days, 
                     child_age_at_start)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    """,
                    p["child_id"],
                    p["family_id"],
                    p["placement_start"],
                    p["placement_end"],
                    p["outcome"],
                    p["disruption"],
                    p["disruption_reason"],
                    p["duration_days"],
                    p["child_age_at_start"],
                )

    logger.info(f"✓ Generated {len(placements)} historical placements")

    # Print summary stats
    disrupted = sum(1 for p in placements if p["disruption"])
    avg_duration = sum(p["duration_days"] for p in placements) / len(placements)

    logger.info(f"  Successful placements: {len(placements) - disrupted}")
    logger.info(f"  Disrupted placements: {disrupted} ({disrupted/len(placements)*100:.1f}%)")
    logger.info(f"  Average duration: {avg_duration:.0f} days ({avg_duration/365:.1f} years)")


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Generate placement history")
    parser.add_argument("--count", type=int, default=300, help="Number of placements to generate")
    args = parser.parse_args()

    # Connect to database
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)

    try:
        logger.info("Fetching children and families...")
        children, families = await fetch_children_and_families(pool)
        logger.info(f"Found {len(children)} children and {len(families)} families")

        if not children or not families:
            logger.error("Cannot generate placements without children and families")
            logger.info("Run these first:")
            logger.info("  python scripts/seed_families.py")
            logger.info("  python scripts/generate_synthetic_foster_children.py")
            return

        logger.info(f"Generating {args.count} placement history records...")
        await generate_placement_history(pool, children, families, args.count)

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
