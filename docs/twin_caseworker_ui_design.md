# Child Digital Twin — Caseworker UI Design

> **Status:** Product design · **Owner:** Product Design  
> **Date:** 2026-06-01  
> **Principle:** Feels like a flight simulator, not a research tool.  
> **Target user:** Frontline caseworker (BSW/MSW), not a data scientist.

---

## Design Principles

1. **No probability jargon.** The words "probability," "percentile," "distribution," "p-value," "CATE," "regression" never appear in the UI. All uncertainty is communicated with plain English phrases and visual bands.
2. **Decision rehearsal, not prediction.** The tool exists to let a caseworker *rehearse* a decision before making it, like a pilot in a simulator. The output is always: "If you do X, here is what typically happens."
3. **One question per session.** The UI is built around a single workflow: pick a child → pick interventions → compare → save for case conference. No dashboards, no overviews.
4. **Uncertainty is visible but not distracting.** Every chart has a confidence ribbon. Every summary has a qualifier: "These patterns are based on X similar children." There is exactly one place where the caseworker can expand to see technical details — and it is hidden behind a small "ⓘ Why does it say that?" link.
5. **"Consult your supervisor" is always in reach.** A persistent CTA button lives in the toolbar throughout the session. Clicking it opens a draft case-conference agenda pre-populated with the current scenario.

---

## Screen 1: Intervention Builder

### Layout

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ [← Back to child profile]  Child Digital Twin — CH-A0427   [Consult supervisor] │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐  │
│  │  What would you like to try?                                            │  │
│  │                                                                          │  │
│  │  You can change up to 3 things at once. Drag options from the tray      │  │
│  │  below onto the workbench. Drop a card to remove it.                    │  │
│  │  ─────────────────────────────────────────────────────────────────────  │  │
│  │                                                                          │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                  │  │
│  │  │ Change       │  │ Increase     │  │ Start        │                  │  │
│  │  │ school       │  │ therapy to   │  │ mentorship   │                  │  │
│  │  │              │  │ weekly       │  │ programme    │                  │  │
│  │  │ ┌─────┐      │  │              │  │              │                  │  │
│  │  │ │Lincoln│    │  │ [weekly ✓]   │  │ [assign ✓]   │                  │  │
│  │  │ │Elem  ▼│    │  │              │  │              │                  │  │
│  │  │ │       │    │  │              │  │              │                  │  │
│  │  │ │Wash   │    │  │              │  │              │  ┌────────────┐  │  │
│  │  │ │Elem  ││    │  │              │  │              │  │ ADD ANOTHER │  │  │
│  │  │ └─────┘      │  │              │  │              │  │  + (2 of 3) │  │  │
│  │  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └────────────┘  │  │
│  │         │                │                 │                            │  │
│  │         └────────────────┴─────────────────┘                            │  │
│  │                           [▶ Run simulation]                            │  │
│  └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘  │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────────┐│
│  │  Intervention tray                                                      ││
│  │                                                                          ││
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐     ││
│  │  │ 🏫      │ │ 👨‍👩‍👧‍👦      │ │ 🩺      │ │ 📞      │ │ 👤      │     ││
│  │  │ School  │ │ Placement│ │ Therapy │ │ Visits  │ │ Mentor  │     ││
│  │  │ change  │ │ change   │ │ increase  │ │ increase │ │ assign   │     ││
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘     ││
│  │                                                                          ││
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐                                 ││
│  │  │ 📋      │ │ 👪      │ │ 💊      │                                 ││
│  │  │ Change  │ │ Sibling │ │ Medication│                                 ││
│  │  │ caseworker│ │ visit    │ │ support   │                                 ││
│  │  │          │ │ increase │ │ plan      │                                 ││
│  │  └──────────┘ └──────────┘ └──────────┘                                 ││
│  └──────────────────────────────────────────────────────────────────────────┘│
├──────────────────────────────────────────────────────────────────────────────┤
│  This tool helps you explore possible outcomes. It does not make decisions.  │
│  Always discuss intervention plans with your supervisor before acting.       │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Component Specifications

**Workbench header**
- **Copy:** "What would you like to try?"
- **Subtitle:** "You can change up to 3 things at once. Drag options from the tray below onto the workbench. Drop a card to remove it."
- **Empty state:** When no interventions are selected, the workbench shows a dashed border area with ghost text: "Drag interventions here to begin."

**Intervention cards** (on workbench, after dragging):
- Each card has a coloured left border: 🟠 school, 🟣 placement, 🟢 therapy, 🔵 visits, 🟡 mentor, ⚪ caseworker, 🩷 sibling, 🔴 medication.
- Card title (bold), then a single configurable parameter below.
- School change card shows a dropdown of available schools in the district (fetched from district API). Default: nearest school with space.
- Placement change card shows a dropdown of available foster families (from `families` table where `available_capacity > 0` and match_score > 50).
- Visit increase card shows a frequency toggle: biweekly ↔ weekly ↔ twice weekly.
- Mentor card shows a single toggle: assign mentor [yes/no].

**Intervention tray** (below workbench):
- 8 intervention types arranged as icon + label tiles.
- Drag-and-drop to move onto the workbench.
- Grayed out when the workbench has 3 cards. Tooltip on hover: "Maximum 3 changes at a time. Remove one to add another."

**"ADD ANOTHER" button** (on workbench):
- Count indicator: "(1 of 3)" / "(2 of 3)" / "(3 of 3)"
- Disabled and grayed at 3. Tooltip at 3: "You've reached the maximum of 3 simultaneous changes. This prevents plans from being too complex to evaluate."

**Run simulation button:**
- Only enabled when 1–3 intervention cards are on the workbench.
- Text: "▶ Run simulation"
- Transitions to a loading state with indeterminate progress bar and text: "Running 1,000 simulated scenarios… This takes about 15 seconds."

**Footer disclaimer (persistent):**
```
This tool helps you explore possible outcomes. It does not make decisions.
Always discuss intervention plans with your supervisor before acting.
```

---

## Screen 2: Outcome Comparison

### Layout

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ [← Change interventions]  Child Digital Twin — CH-A0427   [Consult supervisor] │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────────┐│
│  │  Your plan                                                               ││
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                  ││
│  │  │ Change       │  │ Increase     │  │ Start        │                  ││
│  │  │ school →     │  │ therapy to   │  │ mentorship   │                  ││
│  │  │ Washington   │  │ weekly       │  │ programme    │                  ││
│  │  │ Elementary   │  │              │  │              │                  ││
│  │  └──────────────┘  └──────────────┘  └──────────────┘                  ││
│  └──────────────────────────────────────────────────────────────────────────┘│
│                                                                              │
│  ┌──────────────────────────────┐  ┌──────────────────────────────────────┐  │
│  │  Current trajectory          │  │  With your changes                   │  │
│  │                               │  │                                       │  │
│  │  ┌─────────────────────────┐  │  │  ┌─────────────────────────────────┐ │  │
│  │  │    ┌──┐                 │  │  │  │                  ┌──┐           │ │  │
│  │  │    │  │   ┌──┐          │  │  │  │   ┌──┐          │  │           │ │  │
│  │  │    │  │   │  │  ┌──┐    │  │  │  │   │  │     ┌────┘  │           │ │  │
│  │  │    │  │   │  │  │  │    │  │  │  │   │  │  ┌──┘       │           │ │  │
│  │  │    │  │   │  │  │  │    │  │  │  │   │  │  │          │  ┌──┐    │ │  │
│  │  │    └──┘   └──┘  └──┘    │  │  │  │   └──┘  └──────────┘  │  │    │ │  │
│  │  │ ──────────────────────── │  │  │  │ ───────────────────────└──┘    │ │  │
│  │  │ stability                │  │  │  │ stability                       │ │  │
│  │  │                           │  │  │                                   │ │  │
│  │  │ Today    30 days   90 days│  │  │  │ Today    30 days   90 days      │ │  │
│  │  └─────────────────────────┘  │  │  └─────────────────────────────────┘ │  │
│  │                               │  │                                       │  │
│  │  Summary                       │  │  Summary                              │  │
│  │  "Without changes,             │  │  "With all three changes in place,   │  │
│  │  CH-A0427 is likely to         │  │  CH-A0427 is likely to remain        │  │
│  │  experience a disruption       │  │  stable. The first 30 days may be    │  │
│  │  within the next 90 days.      │  │  difficult — changes of this size    │  │
│  │  Patterns from 180 similar     │  │  are hard at first — but outcomes    │  │
│  │  children show this outcome."  │  │  improve after the transition."      │  │
│  │                               │  │                                       │  │
│  └──────────────────────────────┘  └──────────────────────────────────────┘  │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────────┐│
│  │  What this means                         [ⓘ Why does it say that?]      ││
│  │                                                                          ││
│  │  🟢 This plan is likely to help.                                        ││
│  │                                                                          ││
│  │  Out of 1,000 simulated scenarios:                                      ││
│  │    • 890 showed improvement with these changes                          ││
│  │    • 110 showed no meaningful difference                                 ││
│  │                                                                          ││
│  │  What helped most:                                                       ││
│  │    1. Changing schools (this had the biggest impact)                     ││
│  │    2. Weekly therapy (helped a moderate amount)                          ││
│  │    3. Mentorship (small additional benefit)                              ││
│  │                                                                          ││
│  │  What to watch for:                                                      ││
│  │    Changing school and placement at the same time is a lot for a child. ││
│  │    The first 2–4 weeks may show increased distress before improving.     ││
│  │    Plan for extra support during the transition period.                 ││
│  └──────────────────────────────────────────────────────────────────────────┘│
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────────┐│
│  │  [💾 Save as Scenario A]  [Save as Scenario B]  [Save as Scenario C]    ││
│  │                                                                          ││
│  │  Or [← Change interventions] to try a different combination.            ││
│  └──────────────────────────────────────────────────────────────────────────┘│
├──────────────────────────────────────────────────────────────────────────────┤
│  This tool helps you explore possible outcomes. It does not make decisions.  │
│  Always discuss intervention plans with your supervisor before acting.       │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Component Specifications

**Plan summary bar** (top):
- Shows the active intervention cards in a compact horizontal row.
- Each card is smaller than the builder version with a coloured left border matching the builder.
- "Change interventions" link in the top-left returns to the builder (scenario is preserved in local state).

**Side-by-side charts (core visualisation):**
- Two charts of identical scale: left = current trajectory, right = simulated trajectory.
- X-axis: time in days (Today, 30 days, 60 days, 90 days).
- Y-axis: never labelled with numbers. Instead uses a qualitative band: green zone (top 40% of chart, labelled "stable"), amber zone (middle 30%, labelled "uncertain"), red zone (bottom 30%, labelled "disruption likely").
- **Line:** The median trajectory is a solid white line.
- **Confidence ribbon:** A shaded band around the line. The band is:
  - Narrow when the model is confident (many similar children in training data)
  - Wide when the model is uncertain (few similar children)
  - Labelled with a hover tooltip: "This band shows the range of outcomes seen in similar children. When the band is narrow, the pattern is well-established."
- **Hover states:** Hovering over any point on the line shows a tooltip:
  - "At 30 days: most similar children were [stable / disrupted]"
  - "Range of outcomes in this group: [best case] to [worst case]"

**Summary text (below each chart):**
- Generated by an LLM from a structured template (no free-form generation). The template has four slots:
  1. Outcome direction: "likely to remain stable" / "likely to experience disruption" / "pattern is unclear"
  2. Time qualifier: "within the next 30 days" / "within the next 90 days"
  3. Confidence qualifier: "Patterns from 180 similar children show this outcome" / "Only 25 similar children found — treat this as a rough guide"
  4. Transition note (counterfactual only): "The first 30 days may be difficult — changes of this size are hard at first"
- The template is populated by rules, not an LLM:

```python
def summary_text(trajectory, n_similar, is_counterfactual):
    dominant = trajectory.dominant_outcome(t=90)
    confidence = confidence_phrase(n_similar)
    direction = outcome_phrase(dominant)
    transition = transition_note() if is_counterfactual else ""
    return f"Without changes, {direction} within the next 90 days. {confidence}. {transition}"
```

**Plain-English explanation panel (below charts):**
- Header: "What this means" with a "ⓘ Why does it say that?" link on the right. Clicking the link opens a technical sidebar (Screen 2b) with the model version, number of similar children, and a note: "This tool uses patterns from X historical placements. It is not a guarantee. Always consult your supervisor."
- **Green/amber/red verdict badge:** A prominent emoji-driven badge that summarises the plan:
  - 🟢 "This plan is likely to help" — if probability of benefit > 0.80
  - 🟡 "This may help, but there is uncertainty" — if 0.50 ≤ probability of benefit ≤ 0.80
  - 🔴 "This plan is unlikely to make a meaningful difference" — if probability of benefit < 0.50
- **Simulation source note** (always visible): "Out of 1,000 simulated scenarios:" followed by two bullet points with actual counts (not percentages).
- **Decomposition table:** "What helped most:" — the top 3 interventions ranked by contribution, each with a plain-language description of the effect size.
- **Risk note** (for compound interventions): Always present when 2+ interventions are selected. Highlighted in a light-yellow box with a ⚠️ icon. Contains specific, templated advice based on the combination type:
  - School + placement: "Changing school and placement at the same time is a lot for a child. Plan for extra support during the transition."
  - Placement + caseworker: "A new placement with a new caseworker means the child loses both familiar adults. Consider overlapping visits for the first 2 weeks."
  - Therapy + medication: "Coordinating therapy and medication changes requires close communication between providers. Confirm they are aware of each other's plans."

**Save scenario bar (bottom):**
- Three buttons: "Save as Scenario A", "Save as Scenario B", "Save as Scenario C"
- Each button, when clicked, highlights to show it is saved. The scenario is stored in local storage + synced to the `pending_simulations` field of `child_twin_states`.
- When a slot is already filled, the button shows the scenario name and a ✏️ icon to overwrite.
- Below the buttons: "Or [← Change interventions] to try a different combination."

---

## Screen 2b: Technical Sidebar (Hidden Behind "ⓘ Why does it say that?")

This is the only place where technical details appear. It is a slide-out panel from the right edge.

```
┌──────────────────────────────┐
│ ╳ How this works            │
│                              │
│ This simulation compared    │
│ CH-A0427 to 180 children    │
│ who had similar profiles    │
│ and circumstances.          │
│                              │
│ ────                        │
│ Data source:                 │
│ • 1,842 historical          │
│   placements in Artifex     │
│ • Last updated: 2 days ago  │
│ • Model: twin-v1-2026-06    │
│                              │
│ ────                        │
│ What similar means:          │
│ Children matched on age,    │
│ special needs, incident     │
│ history, school attendance, │
│ and caseworker visit        │
│ patterns.                   │
│                              │
│ ────                        │
│ Important limitations:      │
│ • 180 matches is a          │
│   moderate-sized group.     │
│   Results are moderately    │
│   reliable.                 │
│ • The system does not know  │
│   about this child's        │
│   specific trauma history   │
│   unless it is documented   │
│   in check-in notes.        │
│ • Patterns show what        │
│   happened, not what must   │
│   happen. Every child is    │
│   different.                 │
│                              │
│ [Close]                     │
└──────────────────────────────┘
```

The sidebar is fixed width (320px). It overlays the right side of the screen with a semi-transparent backdrop. The content is entirely templated — no dynamic values that could confuse.

---

## Screen 3: Scenario Save & Case Conference Prep

### Layout

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ [← Back to simulation]  Child Digital Twin — CH-A0427    [Consult supervisor] │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────────┐│
│  │  Saved scenarios for CH-A0427                                           ││
│  │                                                                          ││
│  │  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐      ││
│  │  │ Scenario A        │  │ Scenario B        │  │ Scenario C        │      ││
│  │  │ [empty]           │  │ [empty]           │  │ [empty]           │      ││
│  │  │                   │  │                   │  │                   │      ││
│  │  │ + New Scenario    │  │ + New Scenario    │  │ + New Scenario    │      ││
│  │  └──────────────────┘  └──────────────────┘  └──────────────────┘      ││
│  └──────────────────────────────────────────────────────────────────────────┘│
│                                                                              │
│  [Example filled scenario card:]                                              │
│  ┌──────────────────────────────────────────────────────────────────────────┐│
│  │ ⭐ Scenario A — "Change school + therapy"              [Edit] [Delete]  ││
│  │                                                                          ││
│  │  Changes:                                                                ││
│  │  🟠 School → Washington Elementary                                       ││
│  │  🟢 Therapy → weekly                                                     ││
│  │                                                                          ││
│  │  Expected outcome:                                                       ││
│  │  "With these changes, CH-A0427 is likely to remain stable."              ││
│  │  🟢 This plan is likely to help (890 of 1,000 scenarios improved).      ││
│  │                                                                          ││
│  │  Saved: Jun 1, 2026 at 2:30 PM                                          ││
│  │                                                                          ││
│  │  Caseworker note: |_____________________________________________|       ││
│  │  [Save note]                                                            ││
│  └──────────────────────────────────────────────────────────────────────────┘│
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────────┐│
│  │  [📋 Prepare for case conference]                                       ││
│  │                                                                          ││
│  │  Click to generate a PDF summary of all filled scenarios to share       ││
│  │  with your supervisor and the case conference team.                     ││
│  │                                                                          ││
│  │  The PDF will include:                                                   ││
│  │  • Child overview (name, age, weeks in placement)                       ││
│  │  • Each saved scenario with its outcomes                               ││
│  │  • Side-by-side trajectory charts                                      ││
│  │  • Your caseworker notes                                                ││
│  │  • Data source disclosure: "Based on 1,842 historical placements"      ││
│  │                                                                          ││
│  │  [Generate PDF]  [Generate PDF + Email to supervisor]                   ││
│  └──────────────────────────────────────────────────────────────────────────┘│
├──────────────────────────────────────────────────────────────────────────────┤
│  This tool helps you explore possible outcomes. It does not make decisions.  │
│  Always discuss intervention plans with your supervisor before acting.       │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Component Specifications

**Scenario slot cards (3-column grid):**
- Each is a bordered card with a large "+ New Scenario" prompt (empty state) or a filled scenario summary.
- **Empty state:** Dashed border, ghost text "+ New Scenario", secondary text "Run a simulation and save it here."
- **Filled state:** Star icon + scenario label (A/B/C) at top. Then:
  1. **Intervention list:** Each intervention on its own line with the coloured emoji prefix, school/family name where applicable.
  2. **Outcome summary:** The plain-English outcome string from the simulation result.
  3. **Verdict badge:** Same 🟢/🟡/🔴 badge from Screen 2.
  4. **Saved timestamp:** "Saved: Jun 1, 2026 at 2:30 PM"
  5. **Caseworker note:** A free-text textarea (max 500 chars) where the caseworker can write why they are considering this scenario.
  6. **Save note button:** Saves the note to `child_twin_states.pending_simulations[i].caseworker_note`.

**"Prepare for case conference" panel (below scenarios):**
- Only enabled when at least 1 scenario has been saved.
- Two CTAs: "Generate PDF" and "Generate PDF + Email to supervisor".
- "Generate PDF + Email" opens the system email client with a pre-filled draft:
  - To: supervisor's email (from the caseworker's team assignment)
  - Subject: "Case Conference Prep — CH-A0427 — [caseworker name]"
  - Body: "[Caseworker name] has prepared simulation scenarios for CH-A0427 and is requesting a case conference to discuss the intervention plan."

**Generated PDF structure:**
- Page 1: Child overview (name, age, weeks in placement, current risk level) + data source disclosure
- Page 2–4: Each saved scenario on its own page with the trajectory chart rendered as an embedded SVG, intervention list, outcome summary, and caseworker note
- Page 5: Side-by-side comparison of all scenarios as a single chart (overlaid trajectories with different line colours matching the scenario labels)
- Footer on every page: "This document was generated by the Artifex Child Digital Twin simulation tool. Outcomes are probabilistic and based on historical patterns. They are not guarantees. All intervention plans must be reviewed by a licensed supervisor."

---

## Uncertainty Language Translation Table

| Technical concept | Caseworker-facing language |
|---|---|
| P(disrupt) = 0.72 | "Likely to experience disruption" |
| P(disrupt) = 0.34 | "Likely to remain stable" |
| 95% CI [0.61, 0.83] | Confidence ribbon width + hover: "This band shows the range of outcomes seen in similar children" |
| n = 180 similar children | "Patterns from 180 similar children" |
| n = 25 similar children | "Only 25 similar children found — treat this as a rough guide" |
| Probability of benefit = 0.89 | "890 of 1,000 scenarios improved with these changes" |
| CATE = -0.38 | "This plan is likely to help" / "This may help, but there is uncertainty" |
| Interaction effect = -0.06 | "What to watch for:" + specific transition guidance |
| Robustness value = 0.38 | Never shown to caseworker. Only appears in the audit log. |
| Sensitivity analysis | Never shown. Technical sidebar says: "The system does not know about this child's specific trauma history unless it is documented in check-in notes." |
| Heterogeneous treatment effect | Never shown. Decomposition says: "Changing schools (this had the biggest impact)" |
| Conformal prediction coverage | Never shown. The technical sidebar shows: "Results are moderately reliable" (qualitative mapping: >90% coverage = "well-established pattern", 80–90% = "moderately reliable", <80% = "rough guide") |

---

## Empty & Error States

| State | Behaviour | Copy |
|---|---|---|
| No simulation history (first visit) | Workbench is empty, tray is fully active | "This is your first time using the simulator for CH-A0427. Drag an intervention from the tray below to begin." |
| Insufficient historical data for this demographic group | Simulation shows results but all verdict badges are 🟡 "uncertain" with wide confidence ribbons; technical sidebar appears automatically | "We found fewer similar children for this child's profile than we'd like. Results are less reliable than usual. Consider discussing with your supervisor before making a decision based on this simulation." |
| Model is stale (>7 days since last update) | Red banner across top of builder screen, simulation still runs but with a warning overlay | "⚠️ This child's data has not been updated in 14 days. Simulation results may not reflect their current situation. Please submit a check-in before using this tool." |
| Twin disabled for this child (opt-out) | Builder screen shows a single card, all interactions disabled | "Simulation is not available for CH-A0427. If you believe this is an error, contact your agency administrator." |
| Network error during simulation | Run button reappears with "Retry" label | "Simulation couldn't complete. [Retry]. If this persists, contact IT support." |
| No schools available in district | School change card shows a red border on the dropdown | "No schools with available space found in this district. Contact the school liaison to discuss options." |

---

## Implementation Notes

### Component Tree
```
TwinPage
├── BuilderHeader (back link, child ID, consult supervisor CTA)
├── InterventionBuilder
│   ├── Workbench (drop zone, max 3 cards)
│   ├── InterventionTray (8 draggable options)
│   └── RunButton (disabled until 1+ interventions)
├── OutcomeComparison
│   ├── PlanSummary (horizontal card row)
│   ├── SideBySideCharts
│   │   ├── TrajectoryChart (current)
│   │   └── TrajectoryChart (counterfactual)
│   ├── ExplanationPanel
│   │   ├── VerdictBadge 🟢/🟡/🔴
│   │   ├── SimulationSourceNote
│   │   ├── DecompositionTable
│   │   └── RiskNote (compound only)
│   ├── TechnicalSidebar (slide-out, hidden)
│   └── ScenarioSaveBar
├── ScenarioManager
│   ├── ScenarioCard × 3
│   └── CaseConferencePrep
│       ├── GeneratePDF
│       └── GeneratePDFandEmail
└── FooterDisclaimer (persistent)
```

### Data Flow
```
1. Caseworker selects interventions → state: { interventions: Card[] }
2. Clicks "Run simulation" → POST /api/twin/{child_id}/simulate
   payload: { interventions, horizon_days: 90 }
3. Response: SimulationResult (see twin_simulation_engine_design.md)
4. Frontend renders:
   - Charts from baseline.trajectory + counterfactual.trajectory
   - Summary from effect.probability_of_benefit + n_historical_placements
   - Decomposition from effect.decomposition
   - Risk note from effect.interaction_effect (if compound)
5. Save scenario → PATCH /api/twin/{child_id}/scenarios
   payload: { slot: "A" | "B" | "C", simulation_id, interventions, caseworker_note }
6. Case conference → GET /api/twin/{child_id}/case-conference-pdf
   response: application/pdf (generated server-side via WeasyPrint or Playwright)
```

### Persistence
Scenarios are stored in the `child_twin_states.pending_simulations` JSONB field. Each scenario has:
```json
{
  "slot": "A",
  "label": "Change school + therapy",
  "simulation_id": "sim_a1b2c3d4",
  "interventions": [
    { "type": "school_change", "value": "Washington Elementary" },
    { "type": "therapy_frequency", "value": "weekly" }
  ],
  "outcome_summary": "With these changes, CH-A0427 is likely to remain stable.",
  "verdict": "positive",
  "caseworker_note": "",
  "saved_at": "2026-06-01T14:30:00Z",
  "expires_at": "2026-06-08T14:30:00Z"
}
```

Scenarios expire after 7 days. A yellow banner appears on the scenario management screen: "Scenario A was saved 8 days ago. Consider running a fresh simulation before the case conference."
