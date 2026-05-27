"""
scripts/load_afcars_data.py – Load real foster care data from AFCARS / CSV.

Usage:
    # Fetch from public API (requires valid resource_id):
    python scripts/load_afcars_data.py --source api

    # Load from a local CSV file:
    python scripts/load_afcars_data.py --source csv --file data/families.csv

The script upserts records into the in-memory _FAMILIES list used by
match_child_activity. In production, replace with a PostgreSQL/Redis write.

CSV expected columns:
    family_id, max_age, siblings (0/1), special_needs_trained (0/1),
    experience (high/medium/low), has_animals (0/1), name, location
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from pathlib import Path
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

# Public AFCARS dataset endpoint (Data.gov CKAN API)
AFCARS_URL = "https://data.acf.hhs.gov/api/3/action/datastore_search"
# Replace with the actual resource_id from the AFCARS dataset page
AFCARS_RESOURCE_ID = "your_resource_id_here"


async def fetch_afcars_data(limit: int = 1000) -> list[dict[str, Any]]:
    """
    Fetch de-identified records from the AFCARS public API.
    Returns raw records; caller is responsible for mapping to family dicts.
    """
    params = {"resource_id": AFCARS_RESOURCE_ID, "limit": limit}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(AFCARS_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
        records = data.get("result", {}).get("records", [])
        logger.info("afcars.fetched", count=len(records))
        return records


async def load_families_from_csv(file_path: str) -> list[dict[str, Any]]:
    """
    Load family records from a local CSV file.

    Expected columns: family_id, max_age, siblings, special_needs_trained,
                      experience, has_animals, name, location
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {file_path}")

    families = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                families.append({
                    "family_id":             row["family_id"],
                    "name":                  row.get("name", row["family_id"]),
                    "location":              row.get("location", "Unknown"),
                    "max_age":               int(row["max_age"]),
                    "can_take_siblings":     bool(int(row.get("siblings", 0))),
                    "special_needs_trained": bool(int(row.get("special_needs_trained", 0))),
                    "experience":            row.get("experience", "medium"),
                    "has_animals":           bool(int(row.get("has_animals", 0))),
                })
            except (KeyError, ValueError) as exc:
                logger.warning("afcars.csv_row_error", row=row, error=str(exc))

    logger.info("afcars.csv_loaded", count=len(families), file=file_path)
    return families


async def background_refresh(interval_seconds: int = 900) -> None:
    """
    Background task that refreshes family data every `interval_seconds`.
    Designed to be started as an asyncio task from api/main.py lifespan.
    """
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            # In production: fetch from your DB or the AFCARS API
            # For now, just log that a refresh would happen
            logger.info("afcars.background_refresh_tick",
                        interval_seconds=interval_seconds)
            # fresh = await fetch_afcars_data()
            # update_in_memory_cache(fresh)
        except Exception as exc:  # noqa: BLE001
            logger.warning("afcars.refresh_error", error=str(exc))


async def main(source: str, file: str | None) -> None:
    if source == "api":
        records = await fetch_afcars_data()
        print(json.dumps(records[:3], indent=2))
    elif source == "csv":
        if not file:
            print("ERROR: --file is required when --source=csv")
            return
        families = await load_families_from_csv(file)
        print(f"Loaded {len(families)} families from {file}")
        print(json.dumps(families[:3], indent=2))
    else:
        print(f"Unknown source: {source}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load AFCARS foster care data")
    parser.add_argument("--source", choices=["api", "csv"], default="csv",
                        help="Data source: 'api' for AFCARS API, 'csv' for local file")
    parser.add_argument("--file", default=None,
                        help="Path to CSV file (required when --source=csv)")
    args = parser.parse_args()
    asyncio.run(main(args.source, args.file))
