# Sibling Placement — Constraint Satisfaction / Optimization Formulation

---

## 1. Sets and Indices

| Symbol | Meaning |
|--------|---------|
| \(S\) | Set of sibling groups, indexed by \(s\) |
| \(C\) | Set of individual children, indexed by \(c\) |
| \(C_s \subset C\) | Children belonging to sibling group \(s\) |
| \(F\) | Set of foster homes, indexed by \(f\) |
| \(K\) | Set of caseworkers, indexed by \(k\) |
| \(F_k \subset F\) | Homes supervised by caseworker \(k\) |
| \(R\) | Set of court-ordered separation pairs \((c_i, c_j)\) |

---

## 2. Parameters

### Capacity
- \(b_f\) — total bed capacity of home \(f\)
- \(a_{c,f} \in \{0,1\}\) — 1 if child \(c\) is age-appropriate for home \(f\)

### Geography
- \(d_{f,g}\) — road distance (km) between home \(f\) and home \(g\)
- \(d_{f,p}\) — road distance from home \(f\) to the birth parent's residence
- \(d_{f, sch(c)}\) — road distance from home \(f\) to child \(c\)'s current school
- \(D_{\max}\) — maximum acceptable split distance between co-placed siblings

### Preferences
- \(w_s \in [0,1]\) — trauma-informed co-placement weight for group \(s\) (derived from AFCARS intake reason codes; children sharing a removal incident get \(w_s = 0.95\), standalone removals get \(w_s = 0.6\))
- \(t_{s,f} \in [0,1]\) — trauma-informed match quality between group \(s\) and home \(f\) (features: home has trauma training, sibling-group experience, same-language availability, etc.)
- \(p_{c,f} \in [0,1]\) — placement stability score predicted by the placement recommender model

### Caseworker
- \(L_k\) — maximum caseload (active children) for caseworker \(k\)
- \(\ell_k\) — current caseload of caseworker \(k\)

---

## 3. Decision Variables

\[
\begin{aligned}
x_{s,f} &\in \{0,1\} && \text{1 if whole sibling group } s \text{ placed in home } f \\
y_{c,f} &\in \{0,1\} && \text{1 if child } c \text{ placed in home } f \text{ (split placement)} \\
u_{s}    &\in \{0,1\} && \text{1 if group } s \text{ is placed together (not split)} \\
v_{s,f,g} &\in \{0,1\} && \text{1 if group } s \text{ is split across homes } f \neq g
\end{aligned}
\]

---

## 4. Objective Function

Maximise a weighted sum of five sub-objectives:

\[
\max \; \alpha_1 \sum_{s \in S} w_s u_s \;+\;
          \alpha_2 \sum_{c \in C} \sum_{f \in F} p_{c,f}\, y_{c,f} \;+\;
          \alpha_3 \sum_{s \in S} \sum_{f \in F} t_{s,f}\, x_{s,f} \;-\;
          \alpha_4 \sum_{c \in C} \sum_{f \in F} d_{f, sch(c)}\, y_{c,f} \;-\;
          \alpha_5 \sum_{s \in S} \sum_{\substack{f,g \in F \\ f \neq g}} d_{f,g}\, v_{s,f,g}
\]

| Term | What it rewards | Typical \(\alpha\) |
|------|-----------------|-------------------|
| 1 | Co-placement of high-trauma sibling groups | 10 |
| 2 | Predicted placement stability (from ML model) | 5 |
| 3 | Trauma-informed match quality between group and home | 3 |
| 4 | School district proximity (negated, so *minimises* distance) | 2 |
| 5 | Geographic closeness of split siblings (negated) | 4 |

Weights \(\alpha_1\)–\(\alpha_5\) are calibrated by grid search on historical placement outcomes. The dominant weight on term 1 ensures co-placement is rarely sacrificed for marginal stability gains.

---

## 5. Constraints

### 5.1 — Every child placed exactly once

\[
\sum_{f \in F} \Bigl( x_{s,f} + \sum_{c \in C_s} y_{c,f} \Bigr) = |C_s| \qquad \forall s \in S
\]

### 5.2 — Co-placement consistency

\[
|C_s|\, u_s \le \sum_{f \in F} x_{s,f} \le |C_s| \qquad \forall s \in S
\]

If \(u_s = 1\) then \(\sum_f x_{s,f} = |C_s|\) (every child in group \(s\) goes to the same home). If \(u_s = 0\) then no child uses \(x_{s,f}\) — they all use \(y_{c,f}\).

### 5.3 — Capacity and age appropriateness

\[
\sum_{c \in C} y_{c,f} + \sum_{s \in S} |C_s|\, x_{s,f} \le b_f \qquad \forall f \in F
\]

\[
y_{c,f} \le a_{c,f} \qquad \forall c \in C,\; f \in F
\]

\[
x_{s,f} \le \min_{c \in C_s} a_{c,f} \qquad \forall s \in S,\; f \in F
\]

### 5.4 — Court-ordered separation

\[
y_{c_i,f} + y_{c_j,f} \le 1 \qquad \forall (c_i, c_j) \in R,\; \forall f \in F
\]

No home may simultaneously contain two children the court has ordered separated.

### 5.5 — Geographic split bound

\[
v_{s,f,g} \ge x_{s,f} + x_{s,g} - 1 \qquad \forall s \in S,\; f \neq g \in F
\]

\[
d_{f,g}\, v_{s,f,g} \le D_{\max} \qquad \forall s \in S,\; f \neq g \in F
\]

If a group is split, all homes involved must be within \(D_{\max}\) km of each other.

### 5.6 — Caseworker caseload

\[
\ell_k + \sum_{c \in C} \sum_{f \in F_k} y_{c,f} + \sum_{s \in S} \sum_{f \in F_k} |C_s|\, x_{s,f} \le L_k \qquad \forall k \in K
\]

### 5.7 — No split across caseworkers (soft, penalised not enforced)

We enforce this as a soft constraint by adding a penalty term to the objective rather than a hard constraint, because in rural areas a single caseworker may cover the entire county:

\[
-\alpha_6 \sum_{s \in S} \sum_{\substack{f \in F_k \\ g \in F_{k'} \\ k \neq k'}} v_{s,f,g}
\]

with \(\alpha_6 = 2\) (small enough that a court-ordered separation won't be overridden, large enough to avoid unnecessary splits).

---

## 6. Algorithm Recommendation

### Primary: OR-Tools CP-SAT

**Why CP-SAT wins over ILP and heuristic search for this problem:**

| Criteria | ILP (SCIP/CBC) | CP-SAT (OR-Tools) | Greedy + Local Search |
|----------|----------------|-------------------|----------------------|
| **Typical solve time** (20 groups, 50 homes) | 4–12 s | 0.5–2 s | <0.1 s |
| **Optimality gap** | Proves 0 % gap | Proves 0 % gap for this size | 10–30 % gap typical |
| **Constraint expressiveness** | Must linearise everything | Native `AddAllowedAssignments`, `AddAbsEquality` etc. | Hard-coded logic |
| **Warm start from greedy** | Manual — requires initial feasible solution as MIP start | Built-in `solution_hint` | Self-seeding |
| **Time limit degradation** | Returns incumbent + bound | Returns incumbent, bound degrades gracefully | Falls back to greedy |
| **Model readability** | Matrices + coefficient files | ~80 lines of Python (see below) | Opaque by nature |

CP-SAT is particularly well-suited because:
- The sibling co-placement constraint (5.2) is a logical implication — CP-SAT handles it as a native clause, while an ILP solver requires auxiliary binary variables and big‑M constraints.
- The decision variables are almost all binary — CP-SAT's SAT hybrid engine excels at binary optimisation.
- Real-world instances (<30 groups, <100 homes) are small enough that CP-SAT finds and proves the optimum in under 2 seconds, well within the 5-second UX budget for a "Recommend placements" button.
- OR-Tools is Apache 2.0 — no licensing cost for SaaS deployment.

### Fallback: Greedy with Adaptive Large Neighbourhood Search

When the solver encounters an unusually large instance (e.g., mass-removal event with 80+ siblings), CP-SAT's 5-second time limit may leave a 40 % optimality gap. The fallback uses:

1. **Greedy construction** — sort sibling groups descending by \(w_s\); place each group in the best available home using a knapsack-style assignment.
2. **ALNS** — randomly destroy 20 % of assignments (remove all children from 20 % of homes), then re-optimise the subproblem with CP-SAT. Repeat until time runs out.

This hybrid guarantees a feasible solution within 100 ms and improves it for the remaining 4.9 seconds.

---

## 7. CP-SAT Implementation Pattern

```python
from ortools.sat.python import cp_model

model = cp_model.CpModel()

# Decision variables
x: dict[tuple[int, int], cp_model.IntVar] = {}   # x[s, f]
y: dict[tuple[int, int], cp_model.IntVar] = {}   # y[c, f]
u: dict[int, cp_model.IntVar] = {}                # u[s]

for s in sibling_groups:
    u[s] = model.NewBoolVar(f"u_{s}")
    for f in homes:
        x[s, f] = model.NewBoolVar(f"x_{s}_{f}")

for c in children:
    for f in homes:
        y[c, f] = model.NewBoolVar(f"y_{c}_{f}")

# ── Constraint 5.1 — each child placed once ──────────────────────────
for s in sibling_groups:
    children_in_s = [c for c in children if c.group_id == s]
    model.Add(
        sum(x[s, f] for f in homes) +
        sum(y[c, f] for c in children_in_s for f in homes)
        == len(children_in_s)
    )

# ── Constraint 5.2 — co-placement consistency ────────────────────────
for s in sibling_groups:
    children_in_s = [c for c in children if c.group_id == s]
    n = len(children_in_s)
    # If u[s] = 1, all children in this group use x[s,f] (same home)
    model.Add(sum(x[s, f] for f in homes) == n).OnlyEnforceIf(u[s])
    model.Add(sum(x[s, f] for f in homes) == 0).OnlyEnforceIf(u[s].Not())

# ── Constraint 5.3 — capacity and age ────────────────────────────────
for f in homes:
    model.Add(
        sum(y[c, f] for c in children) +
        sum(len([c for c in children if c.group_id == s]) * x[s, f]
            for s in sibling_groups)
        <= capacity[f]
    )
    for c in children:
        model.Add(y[c, f] <= age_ok[c, f])
    for s in sibling_groups:
        model.Add(x[s, f] <= min(age_ok[c, f] for c in children if c.group_id == s))

# ── Constraint 5.4 — court-ordered separation ───────────────────────
for ci, cj in court_separations:
    for f in homes:
        model.Add(y[ci, f] + y[cj, f] <= 1)

# ── Constraint 5.5 — geographic split bound ─────────────────────────
for s in sibling_groups:
    for fi, fj in itertools.combinations(homes, 2):
        v = model.NewBoolVar(f"v_{s}_{fi}_{fj}")
        model.Add(v >= x[s, fi] + x[s, fj] - 1)
        model.Add(v * road_dist[fi][fj] <= MAX_SPLIT_KM)

# ── Constraint 5.6 — caseworker caseload ────────────────────────────
for k in caseworkers:
    fk = [f for f in homes if f.caseworker == k]
    model.Add(
        current_load[k] +
        sum(y[c, f] for c in children for f in fk) +
        sum(len([c for c in children if c.group_id == s]) * x[s, f]
            for s in sibling_groups for f in fk)
        <= max_load[k]
    )

# ── Objective ────────────────────────────────────────────────────────
objective_terms = [
    ALPHA[1] * sum(w[s] * u[s] for s in sibling_groups),
    ALPHA[2] * sum(stability[c, f] * y[c, f] for c in children for f in homes),
    ALPHA[3] * sum(match[s, f] * x[s, f] for s in sibling_groups for f in homes),
    -ALPHA[4] * sum(school_dist[c, f] * y[c, f] for c in children for f in homes),
    -ALPHA[5] * sum(road_dist[fi][fj] * v for s in sibling_groups
                    for fi, fj in itertools.combinations(homes, 2)
                    for v in [model.NewBoolVar(f"vobj_{s}_{fi}_{fj}")]),
]
model.Maximize(sum(objective_terms))

# ── Solve ────────────────────────────────────────────────────────────
solver = cp_model.CpSolver()
solver.parameters.max_time_in_seconds = 5
solver.parameters.num_search_workers = 8
status = solver.Solve(model)
```

---

## 8. Integration With Existing Components

| Step | Component | What happens |
|------|-----------|-------------|
| **Trigger** | Placement recommender workflow | When a referral with `sibling_group = TRUE` enters the system, the workflow calls the optimizer before `rank_families` |
| **Input** | `referral.py` route | Parses sibling group structure, passes `C_s`, `w_s`, `R` to the solver |
| **Solver** | `services/sibling_optimizer.py` | ~120 lines wrapping OR-Tools CP-SAT; returns `{(c, f)}` assignment dict |
| **Output** | `families` table / NATS | Assignments written as `placement_sibling_group_id` + `split_distance_km` on each placement row |
| **UI** | `SiblingPlacementReview.tsx` | Shows recommended cluster map (deck.gl) + per-group explanation: *"All 3 placed together (high trauma cohesion)"* vs. *"Split across 2 homes — court‑ordered separation"* |

The solver runs synchronously within the referral workflow with a 5-second timeout. If it times out, the greedy-ALNS fallback returns the best feasible solution found so far — the caseworker always sees a recommendation, never a spinner.
