# Predictive Crisis Engine — Dashboard UI Specification

Three dashboard views that transform raw drift signals into **actionable decisions**, presented with calm visual language that avoids alarm fatigue.

---

## 1. Caseworker Alert Panel

**Purpose:** Daily triage — answer "which children need my attention today and why."

### Layout

```
┌────────────────────────────────────────────────────────────┐
│ ⚠ Crisis Alerts                    threshold [▼60▼] [✓ Acknowledge All] │
├────────────────────────────────────────────────────────────┤
│ ┌────────────────────────────────────────────────────────┐ │
│ │ 🔴 CH-A0427 · Age 9 · Placement 14 wks                │ │
│ │ Risk 72% ████████████████████░░░░░░░░  CI [61–82]     │ │
│ │                                                        │ │
│ │ Signals drifting:                                      │ │
│ │  ● Incident severity  ████████··  critical  │ ˃ detail │
│ │  ● School attendance  ██████····  -22% base │ ˃ detail │
│ │  ● Caregiver rapport  ████······  declining │ ˃ detail │
│ │                                                        │ │
│ │ Interventions: [Schedule therapy] [Liaise with school]  │ │
│ │                                            [✓ Acknowledge] │ │
│ ├────────────────────────────────────────────────────────┤ │
│ │ 🟡 CH-B1023 · Age 14 · Placement 6 wks                │ │
│ │ Risk 48% ████████████░░░░░░░░░░░░  CI [38–58]         │ │
│ │ ...                                                    │ │
│ └────────────────────────────────────────────────────────┘ │
│                                          [View all 12 →]   │
└────────────────────────────────────────────────────────────┘
```

### Key Components

| Component | Behaviour |
|---|---|
| **Risk bar** | Full-width horizontal bar, colour-graded from green → amber → red at thresholds 30/60/80. Width = risk score. |
| **Signal chips** | Inline bullets with progress-bar mini-indicators. Left dot: green (stable), amber (drifting), red (critical). |
| **Intervention pills** | Clickable — opens a confirmation dialog ("Schedule therapy review for CH-A0427?"), then creates a workflow event. |
| **Acknowledge button** | Per-card + bulk at header. Acknowledged alerts collapse to compact mode (icon + score only) but stay visible for 24 h. |

### Micro-interactions

- **Hover on a signal chip** → tooltip with raw values: `attendance_rate: 0.70, baseline: 0.92, delta: −0.22`
- **Click "˃ detail"** on a signal → inline expand of last 4 weekly values for that signal (mini-sparkline)
- **Acknowledge** → subtle checkmark animation, risk bar greys to 50% opacity, card slides to bottom of list
- **Auto-dismiss** after 7 days with no new signals or when risk drops below threshold
- **Empty state** when no alerts: green banner "✅ All placements stable — no alerts above 60% threshold"

### Design Rules

- First card is **always** the highest risk, regardless of acknowledgement state
- Only show a signal in the top-3 if its `delta_from_baseline` exceeds ±0.15 (prevents noise)
- Risk score colour uses the fill, not the label: avoid red text for "high" — the bar width communicates severity

---

## 2. Child-Level Risk Detail View

**Purpose:** Investigate — "what's driving this child's risk and what should I do next."

### Layout

```
┌─────────────────────────────────────────────────────────────────┐
│ ← Back to alerts                        CH-A0427 · Age 9       │
│ Crisis Risk: High 72% ──────────────────────────────────────────│
├─────────────────────────────────────────────────────────────────┤
│ ┌─ Risk Gauge ──────┐ ┌─ 90-Day Risk Trend ──────────────────┐ │
│ │                    │ │                                      │ │
│ │     72%            │ │  80 ┤        ╱╲                      │ │
│ │  ┌──────┐         │ │  60 ┤  ╱╲╱   ╲ ╱╲                    │ │
│ │  │high  │         │ │  40 ┤ ╱  ╲╱    ╲╱ ╲                   │ │
│ │  └──────┘         │ │  20 ┤╱              ╲                 │ │
│ │  CI: [61–82]      │ │      └────────────────────────        │ │
│ │                    │ │     May 5    May 12   May 19   May 26 │ │
│ │  ⚠ 7 drifting     │ │     ● Drift index  ─ Risk score       │ │
│ └────────────────────┘ └──────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────┤
│ Signal Breakdown ───────────────────────────────────────────────┤
│ ┌─────────────────────────────────────────────────────────────┐│
│ │ Incident severity    ████████████████████░░░░  42% critical ││
│ │ School attendance    ██████████████░░░░░░░░░░  28% drifting ││
│ │ Caregiver sentiment  ██████████░░░░░░░░░░░░░░  20% drifting ││
│ │ Medication compliance ██████░░░░░░░░░░░░░░░░░░  14% drifting││
│ │ Communication lag    ████░░░░░░░░░░░░░░░░░░░░░   8% stable  ││
│ │ Communication tone   ██░░░░░░░░░░░░░░░░░░░░░░░   3% stable  ││
│ └─────────────────────────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────────────┤
│ Signal Detail — School Attendance ──────────────────────────────┤
│ ┌─────────────────────────────────────────────────────────────┐│
│ │ Current:    70%  │  Baseline:  92%  │  Delta: −22%         ││
│ │ Trend: declining (slope −0.08/wk)                           ││
│ │                                                            ││
│ │ Week 1  ██████████████████████████████ 100%                 ││
│ │ Week 2  ████████████████████████████░  95%  ← baseline avg ││
│ │ Week 3  ██████████████████████░░░░░░░  75%                 ││
│ │ Week 4  ████████████████████░░░░░░░░░  70% ← current       ││
│ │                                                            ││
│ │ Flags: withdrawn, sleeping_in_class, peer_conflict          ││
│ └─────────────────────────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────────────┤
│ Recommended Interventions ──────────────────────────────────────┤
│ ┌─────────────────────────────────────────────────────────────┐│
│ │ [1] Schedule urgent therapy review                          ││
│ │     → runaway ideation flagged 2026-05-21                   ││
│ │     Assign to: [Dr. Martinez ▼]   [Schedule →]            ││
│ │                                                            ││
│ │ [2] Initiate school liaison meeting                         ││
│ │     → attendance 22% below baseline, engagement flags       ││
│ │     Contact: [Springfield Elem ▼]   [Draft email →]       ││
│ │                                                            ││
│ │ [3] Increase caseworker visits to weekly                    ││
│ │     → sentiment declining −0.60 from baseline               ││
│ │     Currently: 1×/month → 4×/month   [Confirm change →]   ││
│ └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

### Key Components

| Component | Description |
|---|---|
| **Risk gauge** | Semicircular gauge (0–100) with colour zones. Needle animates on load. CI shown as translucent band behind needle. |
| **90-day trend chart** | Dual-axis area chart. Risk score (primary, red-orange fill) + drift index overlay (blue line). Grey vertical band marks "today." |
| **Signal breakdown** | Horizontal stacked bar per signal. Width = contribution to composite drift. Colour = status. Click to expand detail. |
| **Signal detail panel** | Expandable section below the breakdown. Shows current value, baseline, delta, weekly sparkline, raw flags list. |
| **Intervention cards** | Numbered cards with action buttons. Each maps to one `recommended_intervention` from the prediction. "Schedule" button opens the relevant workflow modal. |

### Micro-interactions

- **Chart brushing** → drag to zoom on a date range. Double-click to reset.
- **Click a signal bar** → signal detail panel slides open below with an animated height transition. Click again to collapse.
- **Intervention action buttons** → optimistic UI: button shows spinner, then checkmark with "Created" before the API confirms.
- **Refresh icon** in the gauge header → re-fetches `GET /children/{id}/risk-score?include_signals=true`, shows a subtle pulsing border while loading.
- **Empty signal state** → if no drift data exists yet (first 4 weeks): "Building baseline — collecting signal data. Standard monitoring in place."

---

## 3. Supervisor Overview Heatmap

**Purpose:** Caseload triage — "which caseworkers need support, and where are the systemic risk clusters."

### Layout

```
┌─────────────────────────────────────────────────────────────────┐
│ ╳ Caseload Risk Overview                  As of Jun 1, 2026    │
├─────────────────────────────────────────────────────────────────┤
│ ┌─ Summary cards ─────────────────────────────────────────────┐ │
│ │  24  │   6   │   3   │   1   │   1 caseworker with ≥3      │ │
│ │ Total│ High  │ Crit  │ CW    │ high-risk children           │ │
│ │ cases│ risk  │ risk  │ overloaded│ [View caseload →]        │ │
│ └─────────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────┤
│ Caseworker Caseload Heatmap ────────────────────────────────────┤
│                                                                  │
│ Caseworker     ┃  Wk1  Wk2  Wk3  Wk4  Wk5  Wk6  Wk7  Wk8      │
│ ──────────────────────────────────────────────────────────────── │
│ CW-3312        ┃  ░░   ░░   ▒▒   ▒▒   ██   ██   ██   ██    8  │
│   Johnson      ┃  15   18   32   28   45   55   68   72%        │
│ ──────────────────────────────────────────────────────────────── │
│ CW-4419        ┃  ░░   ░░   ░░   ░░   ▒▒   ▒▒   ▒▒   ▒▒    6  │
│   Mitchell     ┃  12   15   22   20   35   38   42   45%        │
│ ──────────────────────────────────────────────────────────────── │
│ CW-5503        ┃  ░░   ░░   ░░   ░░   ░░   ░░   ░░   ░░    5  │
│   Chen         ┃   5    8   10   12   15   12   18   22%        │
│ ──────────────────────────────────────────────────────────────── │
│ CW-2318        ┃  ░░   ░░   ░░   ▒▒   ▒▒   ▒▒   ▒▒   ██    4  │
│   Okonkwo      ┃   8   12   25   30   38   42   55   65%        │
│ ──────────────────────────────────────────────────────────────── │
│ CW-6612        ┃  ░░   ░░   ░░   ░░   ░░   ▒▒   ▒▒   ▒▒    3  │
│   Patel        ┃  10    8   15   18   22   28   35   38%        │
│ ──────────────────────────────────────────────────────────────── │
│              ╱  ╲                                               │
│        Cell colour:  ░░ <30   ▒▒ 30–60   ██ >60    Risk %      │
│                                                                  │
│ ── Each cell = average risk of that caseworker's caseload that week ──│
└─────────────────────────────────────────────────────────────────┘
```

### Key Components

| Component | Description |
|---|---|
| **Summary cards row** | 4 stat cards: total active cases, high-risk count (>60), critical-risk count (>80), overloaded caseworkers (≥3 high-risk). |
| **Heatmap grid** | Rows = caseworkers, Columns = weeks (8-week rolling window). Cell fill = mean risk of that caseworker's caseload that week. |
| **Row detail** | Name + caseload count on the right. Below each row: small type showing the actual numerical scores for each week. |
| **Colour legend** | Fixed at bottom of heatmap: `░ <30   ▒ 30–60   █ >60`. |

### Micro-interactions

- **Hover on a cell** → tooltip: `CW-3312, Week 6: Avg risk 55% (n=5 children). Children: CH-A0427 (72%), CH-B1023 (48%), CH-C0512 (45%)...`
- **Click a cell** → navigates to filtered alert panel showing only that caseworker's children for that week
- **Click a caseworker name** → navigates to their caseload detail view (alert panel filtered by caseworker_id)
- **Auto-refresh** badge at top-right: "Live" / "Updated 3m ago" with a manual refresh button
- **Export** button → downloads the heatmap as PNG or CSV

### Design Rules

- **Never show a caseworker with 0 active cases** — filter them out to prevent misinterpretation
- Cell colour uses a **perceptually uniform gradient** (viridis or turbo) — not red-green, to accommodate colour vision deficiency
- The "overloaded" badge in the summary cards should be the **only** red element on this screen. Everywhere else uses amber > purple > teal progression.

---

## Shared UI Patterns

### Colour Semantics (all views)

| Level | Token | HEX | When |
|---|---|---|---|
| Stable | `--color-success` | `#10b981` | risk < 30 or signal delta within ±0.15 |
| Watching | `--color-warning` | `#f59e0b` | risk 30–60 or signal delta ±0.15–0.3 |
| Elevated | `--color-orange` | `#f97316` | risk 60–80 or signal delta ±0.3–0.5 |
| Critical | `--color-destructive` | `#dc2626` | risk > 80 or signal delta > 0.5 |

**Rule: Never use red for anything below 60.** Reserve red for the top 20% of risk. This prevents alert fatigue.

### Signal Status Labels

| Term | Visual |
|---|---|
| `stable` | Green dot, no icon |
| `drifting` | Amber upward-arrow icon |
| `critical` | Red double-upward-arrow icon |

### Navigation

- Alert panel → click child → detail view → back
- Supervisor heatmap → click cell → alert panel filtered by caseworker+week
- Detail view → "View all alerts" → alert panel
- All views accessible from the sidebar tab "Crisis Engine"

### Empty / Loading / Error States

| State | Pattern |
|---|---|
| **Loading** | Skeleton shimmer matching the exact layout of the component (not a spinner). |
| **Empty** | Illustration + message: e.g. "✅ All placements stable — no alerts above threshold" |
| **Error** | Inline error banner: "Could not load risk data" with retry button. No full-page errors. |
| **No drift data** | "Building baseline — first 4 weeks of data required before drift signals are available." |
| **Stale data** | Banner: "Risk data is 48+ hours old. [Refresh]" if no snapshot in 2 days. |

### Accessibility

- All risk visualisations must include a text alternative (screen reader reads: "Risk score 72 out of 100, high. Three signals drifting: incident severity critical, school attendance drifting...")
- Keyboard navigable: Tab through alert cards, Enter to expand, Escape to collapse
- `prefers-reduced-motion` disables all gauge needle and card animations
