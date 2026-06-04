#!/usr/bin/env python3
"""
Seed the database with realistic demo data:
  - 50 foster families
  - 100 children
  - 200 historical placements
  - 300 check‑ins

Usage:
    python scripts/seed_all.py
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import random
from datetime import date, datetime, timedelta, timezone

import asyncpg
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://artifex:artifex123@localhost:5432/placements"
)

LOCATIONS = [
    "Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island",
    "Newark", "Jersey City", "Paterson", "Elizabeth", "Trenton",
]
SPECIALIZATIONS = [
    "therapeutic", "medical", "behavioral", "adolescent", "sibling",
    "emergency", "teen", "infant", "special_needs", "",
]
LANGUAGES = ["English", "Spanish", "Mandarin", "Arabic", "French", "Russian", "Korean"]
INTAKE_REASONS = [
    "Parental neglect", "Substance abuse in home", "Physical abuse",
    "Emotional abuse", "Abandonment", "Incarceration of parent",
    "Mental health of parent", "Death of parent", "Voluntary placement",
]
SPECIAL_NEEDS_TYPES = [
    "Autism spectrum", "ADHD", "Learning disability", "Physical disability",
    "Emotional disturbance", "Speech impairment", "Hearing impairment", "",
]
FIRST_NAMES = [
    "Emma", "Liam", "Olivia", "Noah", "Ava", "Ethan", "Sophia", "Mason",
    "Isabella", "James", "Mia", "Benjamin", "Charlotte", "Lucas", "Amelia",
    "Henry", "Harper", "Alexander", "Evelyn", "Daniel", "Abigail", "Matthew",
    "Emily", "Jackson", "Ella", "Logan", "Avery", "David", "Scarlett", "Joseph",
]
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson",
    "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
]
FAMILY_NAMES = [
    "The {0} Family", "{0} Household", "{0} & {1} Foster Home",
]
FAMILY_FIRST_NAMES = [
    "James", "Maria", "David", "Sarah", "Michael", "Patricia", "Robert",
    "Jennifer", "William", "Linda", "Richard", "Barbara", "Joseph", "Elizabeth",
    "Thomas", "Margaret", "Christopher", "Sandra", "Daniel", "Ashley",
]
FAMILY_LAST_NAMES = [
    "Thompson", "Garcia", "Martinez", "Robinson", "Clark", "Lewis", "Lee",
    "Walker", "Hall", "Allen", "Young", "King", "Wright", "Hill", "Scott",
    "Green", "Adams", "Baker", "Nelson", "Carter",
]
DISRUPTION_REASONS = [
    "Family requested removal", "Child behavioral issues",
    "Family unable to meet needs", "Allegation of abuse/neglect",
    "Family relocation", "Therapeutic needs exceeded family capacity",
    "Child safety concern", "Family stress and overwhelm",
    "Placement incompatibility", "Emergency removal",
]
SUCCESSFUL_OUTCOMES = [
    "Reunification", "Guardianship", "Adoption",
    "Emancipation at age 18", "Permanent placement - long term",
]


def _family_id(i: int) -> str:
    return f"FAM-{i:04d}"


def _child_id(i: int) -> str:
    return f"CH-{i:04d}"


async def seed_families(pool: asyncpg.Pool, count: int = 50) -> list[dict]:
    logger.info("Seeding %d families …", count)
    rows = []
    for i in range(count):
        fname = random.choice(FAMILY_FIRST_NAMES)
        lname = random.choice(FAMILY_LAST_NAMES)
        name_template = random.choice(FAMILY_NAMES)
        name = name_template.format(lname, fname)
        location = random.choice(LOCATIONS)
        capacity = random.choices([1, 2, 3, 4], weights=[0.2, 0.5, 0.2, 0.1])[0]
        exp = random.choices(
            ["new", "experienced", "expert"], weights=[0.3, 0.5, 0.2]
        )[0]
        languages = random.sample(LANGUAGES, random.randint(1, 3))
        rows.append({
            "family_id": _family_id(i + 1),
            "name": name,
            "location": location,
            "latitude": round(40.7 + random.uniform(-0.5, 0.5), 4),
            "longitude": round(-74.0 + random.uniform(-0.5, 0.5), 4),
            "capacity": capacity,
            "available_capacity": capacity,
            "total_capacity": capacity,
            "active": True,
            "experience": exp,
            "experience_level": exp,
            "specializations": random.choice(SPECIALIZATIONS),
            "languages": ", ".join(languages),
            "languages_arr": languages,
            "special_needs_trained": random.random() < 0.4,
            "accepts_siblings": random.random() < 0.5,
            "sibling_group_capable": random.random() < 0.4,
            "home_type": random.choices(
                ["family", "single_parent", "group_home", "therapeutic"],
                weights=[0.6, 0.2, 0.1, 0.1],
            )[0],
            "emergency_available": random.random() < 0.3,
            "max_age": random.choices(
                [14, 16, 18, 21], weights=[0.2, 0.4, 0.3, 0.1]
            )[0],
            "can_take_siblings": random.random() < 0.5,
            "has_animals": random.random() < 0.4,
        })
    async with pool.acquire() as conn:
        for r in rows:
            await conn.execute(
                """
                INSERT INTO families
                    (family_id, name, location, latitude, longitude,
                     capacity, available_capacity, total_capacity, active,
                     experience, experience_level, specializations,
                     languages, languages_arr, special_needs_trained,
                     accepts_siblings, sibling_group_capable, home_type,
                     emergency_available, max_age, can_take_siblings, has_animals)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22)
                ON CONFLICT (family_id) DO NOTHING
                """,
                r["family_id"], r["name"], r["location"],
                r["latitude"], r["longitude"],
                r["capacity"], r["available_capacity"], r["total_capacity"],
                r["active"],
                r["experience"], r["experience_level"], r["specializations"],
                r["languages"], r["languages_arr"],
                r["special_needs_trained"],
                r["accepts_siblings"], r["sibling_group_capable"],
                r["home_type"],
                r["emergency_available"], r["max_age"],
                r["can_take_siblings"], r["has_animals"],
            )
    logger.info("  ✓ %d families inserted", len(rows))
    return rows


async def seed_children(pool: asyncpg.Pool, count: int = 100) -> list[dict]:
    logger.info("Seeding %d children …", count)
    rows = []
    for i in range(count):
        gender = random.choice(["Male", "Female", "Non-binary"])
        age = random.choices(
            range(1, 18),
            weights=[2, 3, 4, 5, 6, 6, 6, 6, 6, 6, 5, 5, 4, 4, 3, 3, 2],
        )[0]
        first_name = random.choice(FIRST_NAMES)
        last_name = random.choice(LAST_NAMES)
        special_needs = random.random() < 0.35
        special_needs_text = (
            random.choice(SPECIAL_NEEDS_TYPES) if special_needs else ""
        )
        sibling_group = random.random() < 0.2
        languages = random.sample(LANGUAGES, random.randint(1, 2))
        rows.append({
            "child_id": _child_id(i + 1),
            "first_name": first_name,
            "last_name": last_name,
            "age": age,
            "gender": gender,
            "special_needs": special_needs,
            "sibling_group": sibling_group,
            "sibling_count": random.randint(1, 3) if sibling_group else 0,
            "location": random.choice(LOCATIONS),
            "languages": ", ".join(languages),
            "languages_arr": languages,
            "medical_needs": special_needs_text,
            "behavioral_support": random.choice(
                ["therapy", "counseling", "medication", "behavioral_plan", ""]
            ),
            "intake_reason": random.choice(INTAKE_REASONS),
            "emergency_level": random.choices(
                ["normal", "elevated", "urgent"], weights=[0.7, 0.2, 0.1]
            )[0],
            "school_continuity": random.random() < 0.5,
            "notes": "Synthetic seed record" if random.random() < 0.3 else "",
        })
    async with pool.acquire() as conn:
        for r in rows:
            await conn.execute(
                """
                INSERT INTO children
                    (child_id, first_name, last_name, age, gender,
                     special_needs, sibling_group, sibling_count,
                     location, languages, languages_arr,
                     medical_needs, behavioral_support, intake_reason,
                     emergency_level, school_continuity, notes)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)
                ON CONFLICT (child_id) DO NOTHING
                """,
                r["child_id"], r["first_name"], r["last_name"],
                r["age"], r["gender"],
                r["special_needs"], r["sibling_group"], r["sibling_count"],
                r["location"], r["languages"], r["languages_arr"],
                r["medical_needs"], r["behavioral_support"], r["intake_reason"],
                r["emergency_level"], r["school_continuity"], r["notes"],
            )
    logger.info("  ✓ %d children inserted", len(rows))
    return rows


async def seed_placement_history(
    pool: asyncpg.Pool,
    children: list[dict],
    families: list[dict],
    count: int = 200,
) -> None:
    logger.info("Seeding %d historical placements …", count)
    today = date.today()
    inserted = 0
    async with pool.acquire() as conn:
        async with conn.transaction():
            for _ in range(count):
                child = random.choice(children)
                family = random.choice(families)
                days_back = random.randint(30, 365 * 4)
                start = today - timedelta(days=days_back)
                duration = random.choices(
                    [random.randint(30, 90), random.randint(90, 730), random.randint(730, 1825)],
                    weights=[0.15, 0.65, 0.20],
                )[0]
                end = start + timedelta(days=duration)
                if end > today:
                    end = today - timedelta(days=random.randint(1, 30))
                    duration = (end - start).days

                disrupted = random.random() < 0.10
                outcome = (
                    random.choice(DISRUPTION_REASONS)
                    if disrupted
                    else random.choice(SUCCESSFUL_OUTCOMES)
                )
                age_at_start = max(
                    1, child.get("age", 10) - (duration // 365)
                )
                await conn.execute(
                    """
                    INSERT INTO placement_history
                        (child_id, family_id, placement_start, placement_end,
                         outcome, disruption, disruption_reason,
                         duration_days, child_age_at_start)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                    """,
                    child["child_id"], family["family_id"],
                    start, end, outcome, disrupted,
                    outcome if disrupted else None,
                    duration, age_at_start,
                )
                inserted += 1
    logger.info("  ✓ %d placements inserted", inserted)


async def seed_check_ins(pool: asyncpg.Pool, children: list[dict], count: int = 300) -> None:
    logger.info("Seeding %d check-ins …", count)
    now = datetime.now(timezone.utc)
    inserted = 0
    async with pool.acquire() as conn:
        async with conn.transaction():
            for _ in range(count):
                child = random.choice(children)
                minutes_ago = random.randint(0, 90 * 24 * 60)
                ts = now - timedelta(minutes=minutes_ago)
                await conn.execute(
                    """
                    INSERT INTO check_ins
                        (child_id, mood_score, incident_reported, notes, timestamp)
                    VALUES ($1,$2,$3,$4,$5)
                    """,
                    child["child_id"],
                    random.choices(
                        [1, 2, 3, 4, 5],
                        weights=[0.05, 0.1, 0.4, 0.3, 0.15],
                    )[0],
                    random.random() < 0.08,
                    random.choice(
                        ["Doing well", "Had a good day", "Quiet today",
                         "A bit anxious", "Needs extra attention", ""]
                    ),
                    ts,
                )
                inserted += 1
    logger.info("  ✓ %d check-ins inserted", inserted)


async def main():
    parser = argparse.ArgumentParser(
        description="Seed database with demo data"
    )
    parser.add_argument(
        "--families", type=int, default=50,
        help="Number of families (default 50)"
    )
    parser.add_argument(
        "--children", type=int, default=100,
        help="Number of children (default 100)"
    )
    parser.add_argument(
        "--placements", type=int, default=200,
        help="Number of historical placements (default 200)"
    )
    parser.add_argument(
        "--checkins", type=int, default=300,
        help="Number of check-ins (default 300)"
    )
    args = parser.parse_args()

    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    try:
        families = await seed_families(pool, args.families)
        children = await seed_children(pool, args.children)
        await seed_placement_history(pool, children, families, args.placements)
        await seed_check_ins(pool, children, args.checkins)
        logger.info("Seeding complete.")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
