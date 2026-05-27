#!/usr/bin/env python3
"""
Simulate real-time foster care referrals from the synthetic JSON file.

Reads data/synthetic_foster_children.json and sends child_referral events
to the /events endpoint at a controlled rate.

Usage:
    python scripts/simulate_foster_events_from_json.py            # 50 children, 2s delay
    python scripts/simulate_foster_events_from_json.py 100 1.5    # 100 children, 1.5s delay
    python scripts/simulate_foster_events_from_json.py --count 200 --delay 0.5 --checkins 2
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
from pathlib import Path

import httpx

BASE_URL = "http://localhost:8000"

NOTES_POOL = [
    "Settling in well, made a friend at school.",
    "Having nightmares, seems anxious.",
    "Happy with the new family, bonding well.",
    "Acting out at school, refusing to do homework.",
    "Thriving — joined a sports team.",
    "Aggressive behaviour reported, needs counselling.",
    "Improving steadily, attends all activities.",
    "Crisis call last night, emergency intervention needed.",
    "Quiet but stable, no major concerns.",
    "Runaway attempt, returned safely.",
]


async def send_event(
    client: httpx.AsyncClient, event_type: str, data: dict
) -> dict:
    resp = await client.post(
        f"{BASE_URL}/events",
        json={"type": event_type, "data": data},
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json()


async def main(num_children: int, delay_seconds: float, num_checkins: int) -> None:
    json_path = Path("data/synthetic_foster_children.json")
    if not json_path.exists():
        print("Synthetic data not found. Run first:")
        print("  python scripts/generate_synthetic_foster_children.py")
        return

    with open(json_path, encoding="utf-8") as f:
        all_children = json.load(f)

    sample = random.sample(all_children, min(num_children, len(all_children)))
    print(f"\n📋 Sending {len(sample)} child referral(s) from {json_path.name}\n")

    sent_ids: list[str] = []

    async with httpx.AsyncClient() as client:
        # ── Step 1: Send referrals ────────────────────────────────────────────
        for child in sample:
            event_data = {
                "child_id":       child["child_id"],
                "age":            child["age"],
                "age_group":      child["age_group"],
                "removal_reason": child["removal_reason"],
                "siblings":       child["siblings"],
                "special_needs":  child["special_needs"],
            }
            try:
                result = await send_event(client, "child_referral", event_data)
                icon = "✓"
                sent_ids.append(child["child_id"])
            except Exception as exc:  # noqa: BLE001
                result = {"error": str(exc)}
                icon = "✗"

            sn_flag = "🔴 SN" if child["special_needs"] else "   "
            print(
                f"  {icon} {sn_flag} {child['child_id']} "
                f"age={child['age']:>2} siblings={child['siblings']} "
                f"reason={child['removal_reason'][:20]:<20} → {result}"
            )
            await asyncio.sleep(delay_seconds)

        if not sent_ids:
            print("\nNo referrals sent successfully.")
            return

        # ── Step 2: Wait for matching ─────────────────────────────────────────
        wait = max(15, int(delay_seconds * len(sent_ids) * 0.5))
        print(f"\n⏳ Waiting {wait}s for placements to be matched...\n")
        await asyncio.sleep(wait)

        # ── Step 3: Send check-ins ────────────────────────────────────────────
        if num_checkins > 0:
            print(f"📝 Sending {num_checkins} check-in(s) per child...\n")
            for child_id in sent_ids:
                workflow_id = f"foster-{child_id}"
                for week in range(1, num_checkins + 1):
                    score = random.randint(1, 5)
                    notes = random.choice(NOTES_POOL)
                    try:
                        result = await send_event(client, "check_in", {
                            "workflow_id": workflow_id,
                            "score":       score,
                            "notes":       notes,
                        })
                        icon = "🟢" if score >= 4 else ("🟡" if score == 3 else "🔴")
                        print(
                            f"  {icon} Week {week} | {child_id} | "
                            f"score={score} | \"{notes[:45]}...\" → {result}"
                        )
                    except Exception as exc:  # noqa: BLE001
                        print(f"  ✗ check_in failed for {child_id}: {exc}")
                    await asyncio.sleep(1.0)

        # ── Step 4: Placement snapshot ────────────────────────────────────────
        print("\n📊 Current placement snapshot:\n")
        try:
            resp = await client.get(f"{BASE_URL}/foster/placements", timeout=10.0)
            placements = resp.json().get("placements", [])
            if placements:
                for p in placements:
                    family = p.get("family", {})
                    risk   = p.get("risk_score", 0)
                    icon   = "🔴" if risk > 75 else ("🟡" if risk > 40 else "🟢")
                    print(
                        f"  {icon} Child {p.get('child_id'):<12} → "
                        f"Family {family.get('family_id', '?'):<15} "
                        f"Risk {risk:.0f}%"
                    )
            else:
                print("  (no placements yet — activities may still be processing)")
        except Exception as exc:  # noqa: BLE001
            print(f"  Could not fetch placements: {exc}")

    print(f"\n✅ Simulation complete.")
    print(f"   Dashboard WebSocket : ws://localhost:8000/ws/dashboard")
    print(f"   Placements REST     : GET http://localhost:8000/foster/placements")
    print(f"   Temporal UI         : http://localhost:8233\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Simulate foster care referrals from synthetic JSON data"
    )
    parser.add_argument("--count",    type=int,   default=50,  help="Number of children to send")
    parser.add_argument("--delay",    type=float, default=2.0, help="Seconds between referrals")
    parser.add_argument("--checkins", type=int,   default=1,   help="Check-ins per child (0 to skip)")
    # Also support positional args for quick use: script.py 100 1.5
    parser.add_argument("count_pos",  type=int,   nargs="?",   help=argparse.SUPPRESS)
    parser.add_argument("delay_pos",  type=float, nargs="?",   help=argparse.SUPPRESS)
    args = parser.parse_args()

    count = args.count_pos or args.count
    delay = args.delay_pos or args.delay

    asyncio.run(main(count, delay, args.checkins))
