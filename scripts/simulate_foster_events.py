"""
simulate_foster_events.py – Send realistic simulated foster care events to the API.

Usage:
    python scripts/simulate_foster_events.py [--children 3] [--checkins 2]

This script:
  1. Creates N simulated child referrals (starts a FosterPlacementWorkflow each).
  2. Waits for placements to be matched.
  3. Sends weekly check-ins with varied scores and notes.
  4. Optionally triggers a high-risk scenario to test alerting.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import uuid

import httpx

BASE_URL = "http://localhost:8000"

NOTES_POOL = [
    "Settling in well, made a friend at school.",
    "Having nightmares, seems anxious.",
    "Happy with the new family, bonding well.",
    "Acting out at school, refusing to do homework.",
    "Thriving – joined a sports team.",
    "Aggressive behaviour reported, needs counselling.",
    "Improving steadily, attends all activities.",
    "Crisis call last night, emergency intervention needed.",
    "Quiet but stable, no major concerns.",
    "Runaway attempt, returned safely.",
]


async def send_event(client: httpx.AsyncClient, event_type: str, data: dict) -> dict:
    resp = await client.post(f"{BASE_URL}/events", json={"type": event_type, "data": data})
    resp.raise_for_status()
    return resp.json()


async def main(num_children: int, num_checkins: int) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        child_ids: list[str] = []

        # ── Step 1: Create child referrals ────────────────────────────────────
        print(f"\n📋 Creating {num_children} child referral(s)...\n")
        for i in range(num_children):
            child_id = f"C{uuid.uuid4().hex[:6].upper()}"
            age      = random.randint(3, 17)
            siblings = random.randint(0, 2)
            special  = random.choice([True, False])

            result = await send_event(client, "child_referral", {
                "child_id":     child_id,
                "age":          age,
                "siblings":     siblings,
                "special_needs": special,
            })
            child_ids.append(child_id)
            print(
                f"  ✓ Child {child_id} | age={age} siblings={siblings} "
                f"special_needs={special} → {result}"
            )
            await asyncio.sleep(0.5)

        # ── Step 2: Wait for matching to complete ─────────────────────────────
        print(f"\n⏳ Waiting 5 s for placements to be matched...\n")
        await asyncio.sleep(5)

        # ── Step 3: Send check-ins ────────────────────────────────────────────
        print(f"📝 Sending {num_checkins} check-in(s) per child...\n")
        for child_id in child_ids:
            workflow_id = f"foster-{child_id}"
            for week in range(1, num_checkins + 1):
                score = random.randint(1, 5)
                notes = random.choice(NOTES_POOL)
                result = await send_event(client, "check_in", {
                    "workflow_id": workflow_id,
                    "score":       score,
                    "notes":       notes,
                })
                risk_indicator = "🔴" if score <= 2 else ("🟡" if score == 3 else "🟢")
                print(
                    f"  {risk_indicator} Week {week} | {child_id} | "
                    f"score={score} | \"{notes[:50]}...\" → {result}"
                )
                await asyncio.sleep(1)

        # ── Step 4: Check placement snapshot ─────────────────────────────────
        print("\n📊 Current placement snapshot:\n")
        resp = await client.get(f"{BASE_URL}/foster/placements")
        placements = resp.json().get("placements", [])
        if placements:
            for p in placements:
                print(
                    f"  Child {p.get('child_id')} → "
                    f"Family {p.get('family', {}).get('family_id', '?')} | "
                    f"Risk {p.get('risk_score', 0):.0f}%"
                )
        else:
            print("  (no placements yet – activities may still be processing)")

        print("\n✅ Simulation complete.\n")
        print(f"   Dashboard WebSocket : ws://localhost:8000/ws/dashboard")
        print(f"   Placements REST     : GET http://localhost:8000/foster/placements")
        print(f"   Temporal UI         : http://localhost:8233\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simulate foster care events")
    parser.add_argument("--children",  type=int, default=3, help="Number of child referrals")
    parser.add_argument("--checkins",  type=int, default=2, help="Check-ins per child")
    args = parser.parse_args()
    asyncio.run(main(args.children, args.checkins))
