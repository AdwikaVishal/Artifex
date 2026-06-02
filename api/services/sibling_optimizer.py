"""
api/services/sibling_optimizer.py – Sibling Placement Optimizer.

Formulates the sibling placement problem as a CP-SAT model and returns
the best k assignments with per-constraint score breakdowns.

Usage
─────
    optimizer = SiblingPlacementOptimizer()
    result = optimizer.optimize(siblings, available_homes, constraints)

    result.best       # Assignment dict: {child_id: home_id}
    result.alternatives  # Top 3 with trade-off explanations
    result.scores     # Per-constraint breakdown for each option
"""

from __future__ import annotations

import itertools
import math
import time
from dataclasses import dataclass, field
from typing import Any

from ortools.sat.python import cp_model

# ── Constants ─────────────────────────────────────────────────────────────────
MAX_SPLIT_KM = 50          # maximum distance between split-placement homes
SOLVER_TIMEOUT_S = 5       # wall-clock time limit per solve
ALPHA: list[float] = [0, 10.0, 5.0, 3.0, 2.0, 4.0, 2.0]
# Indices: 1=co-placement, 2=stability, 3=trauma match,
#          4=school_dist (neg), 5=split_dist (neg),
#          6=cross_caseworker (neg)

TOP_K = 3                  # number of alternatives to return


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class Child:
    child_id: str
    sibling_group_id: str
    age: int
    gender: str
    special_needs: bool
    trauma_score: float           # 0..1 (1 = highest)

    @property
    def key(self) -> str:
        return self.child_id


@dataclass
class FosterHome:
    home_id: str
    name: str
    lat: float
    lng: float
    total_beds: int
    current_occupancy: int
    age_min: int
    age_max: int
    accepts_special_needs: bool
    caseworker_id: str
    has_trauma_training: bool = False
    has_sibling_experience: bool = False

    @property
    def available_beds(self) -> int:
        return self.total_beds - self.current_occupancy

    @property
    def key(self) -> str:
        return self.home_id


@dataclass
class Constraints:
    court_separations: list[tuple[str, str]] = field(default_factory=list)
    # Pairs of child IDs the court has ordered must NOT share a home.
    max_split_km: float = MAX_SPLIT_KM
    # Hard upper bound on distance between homes if a group is split.
    preferred_homes: dict[str, list[str]] = field(default_factory=dict)
    # Child_id → list of preferred home_ids (e.g. relative placements).


@dataclass
class ScoreBreakdown:
    co_placement: float = 0.0
    trauma_match: float = 0.0
    stability: float = 0.0
    school_proximity: float = 0.0
    split_distance: float = 0.0
    caseworker_cohesion: float = 0.0
    total: float = 0.0


@dataclass
class PlacementOption:
    assignment: dict[str, str]      # child_id → home_id
    score: ScoreBreakdown
    group_status: dict[str, str]    # group_id → "together" | "split" | "split_across_cw"
    infeasible_reason: str = ""


@dataclass
class OptimizationResult:
    best: PlacementOption
    alternatives: list[PlacementOption]
    solver_status: str
    solve_time_ms: float


# ── Helpers ───────────────────────────────────────────────────────────────────

def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two lat/lng points in km."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * \
        math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def road_distance_km(h1: FosterHome, h2: FosterHome) -> float:
    """Return estimated road distance (haversine × 1.4 detour factor)."""
    return haversine_km(h1.lat, h1.lng, h2.lat, h2.lng) * 1.4


# ── Solver ────────────────────────────────────────────────────────────────────

class SiblingPlacementOptimizer:
    """
    Formulate and solve the sibling placement problem.

    The model is a weighted Max-CSP built on OR-Tools CP-SAT.
    """

    def __init__(self, alpha: list[float] | None = None) -> None:
        self.alpha = alpha or ALPHA

    # ── Public API ────────────────────────────────────────────────────────────

    def optimize(
        self,
        children: list[Child],
        homes: list[FosterHome],
        constraints: Constraints | None = None,
    ) -> OptimizationResult:
        """Find the best placement assignment and top-k alternatives."""
        constraints = constraints or Constraints()
        t0 = time.monotonic()

        # Build groups
        groups: dict[str, list[Child]] = {}
        for c in children:
            groups.setdefault(c.sibling_group_id, []).append(c)

        # Pre-compute age-appropriateness and match scores
        age_ok: dict[tuple[str, str], bool] = {}
        match_score: dict[tuple[str, str], float] = {}
        for c in children:
            for h in homes:
                ok = h.age_min <= c.age <= h.age_max
                age_ok[(c.key, h.key)] = ok
                # Trauma match: home with trauma training × higher trauma child
                base = 0.5
                if c.trauma_score > 0.7 and h.has_trauma_training:
                    base = 0.9
                elif c.trauma_score > 0.4 and h.has_sibling_experience:
                    base = 0.7
                match_score[(c.key, h.key)] = base

        # Stats
        group_ids = list(groups.keys())
        home_keys = [h.key for h in homes]
        child_keys = [c.key for c in children]

        # Solve best
        best_option = self._solve_one(
            children, homes, groups, group_ids, home_keys, child_keys,
            age_ok, match_score, constraints,
            forbid_assignment=None,
        )

        if best_option is None:
            # No feasible solution at all
            empty = PlacementOption(
                assignment={},
                score=ScoreBreakdown(),
                group_status={},
                infeasible_reason=self._diagnose_infeasibility(
                    children, homes, groups, constraints,
                ),
            )
            return OptimizationResult(
                best=empty,
                alternatives=[],
                solver_status="INFEASIBLE",
                solve_time_ms=(time.monotonic() - t0) * 1000,
            )

        # Find alternatives by forbidding previous solutions
        alternatives: list[PlacementOption] = []
        previous_assignments: list[dict[str, str]] = [best_option.assignment]

        for _ in range(TOP_K - 1):
            option = self._solve_one(
                children, homes, groups, group_ids, home_keys, child_keys,
                age_ok, match_score, constraints,
                forbid_assignment=previous_assignments,
            )
            if option is None:
                break
            alternatives.append(option)
            previous_assignments.append(option.assignment)

        solve_time = (time.monotonic() - t0) * 1000

        return OptimizationResult(
            best=best_option,
            alternatives=alternatives,
            solver_status="OPTIMAL" if len(alternatives) == TOP_K - 1 else "FEASIBLE",
            solve_time_ms=solve_time,
        )

    # ── Single solve ──────────────────────────────────────────────────────────

    def _solve_one(
        self,
        children: list[Child],
        homes: list[FosterHome],
        groups: dict[str, list[Child]],
        group_ids: list[str],
        home_keys: list[str],
        child_keys: list[str],
        age_ok: dict[tuple[str, str], bool],
        match_score: dict[tuple[str, str], float],
        constraints: Constraints,
        forbid_assignment: list[dict[str, str]] | None,
    ) -> PlacementOption | None:
        """Build and solve one CP-SAT model, optionally forbidding prior solutions."""

        # ── Group metadata ───────────────────────────────────────────
        group_sizes = {gid: len(members) for gid, members in groups.items()}
        # Trauma score for a group = max trauma among its members
        group_trauma = {
            gid: max(c.trauma_score for c in members)
            for gid, members in groups.items()
        }

        # ── Model ────────────────────────────────────────────────────
        model = cp_model.CpModel()

        # Decision variables
        #   x[gid, hk] = 1 if whole group gid → home hk
        x: dict[tuple[str, str], cp_model.IntVar] = {}
        #   y[ck, hk] = 1 if individual child ck → home hk
        y: dict[tuple[str, str], cp_model.IntVar] = {}
        #   u[gid] = 1 if group gid is placed together (not split)
        u: dict[str, cp_model.IntVar] = {}

        for gid in group_ids:
            u[gid] = model.NewBoolVar(f"u_{gid}")
            for hk in home_keys:
                x[gid, hk] = model.NewBoolVar(f"x_{gid}_{hk}")

        for ck in child_keys:
            for hk in home_keys:
                y[ck, hk] = model.NewBoolVar(f"y_{ck}_{hk}")

        # ── Constraint 1: Every child placed exactly once ────────────
        # Each child is either part of a whole-group placement (the group
        # variable u[gid] = 1 and x[gid, hk] routes them all to one home)
        # OR an individual split placement (u[gid] = 0, each child uses
        # y[ck, hk]).  The two paths are mutually exclusive per child.
        for gid in group_ids:
            for c in groups[gid]:
                model.Add(
                    sum(y[c.key, hk] for hk in home_keys) + u[gid] == 1
                )

        # ── Constraint 2: Whole-group assignment count ───────────────
        # If u[gid] = 1, exactly one home hosts the entire sibling group
        # (one x variable is 1).  If u[gid] = 0, no home hosts the whole
        # group — all children are placed individually via y.
        for gid in group_ids:
            model.Add(
                sum(x[gid, hk] for hk in home_keys) == u[gid]
            )

        # ── Constraint 3: Home capacity ──────────────────────────────
        # Total children assigned to a home (both whole-group and
        # individual) may not exceed available beds.
        home_children: dict[str, list[str]] = {}
        for ck in child_keys:
            c_obj = next(c for c in children if c.key == ck)
            home_children.setdefault(c_obj.sibling_group_id, [])
        for hk in home_keys:
            h_obj = next(h for h in homes if h.key == hk)
            model.Add(
                sum(y[ck, hk] for ck in child_keys) +
                sum(group_sizes[gid] * x[gid, hk] for gid in group_ids)
                <= h_obj.available_beds
            )

        # ── Constraint 4: Age appropriateness ────────────────────────
        # A child may only go to a home whose age range includes them.
        for ck in child_keys:
            for hk in home_keys:
                if not age_ok.get((ck, hk), False):
                    model.Add(y[ck, hk] == 0)
        for gid in group_ids:
            for hk in home_keys:
                members_ok = [age_ok.get((c.key, hk), False) for c in groups[gid]]
                # Group can only be placed whole if EVERY member is age-ok
                if not all(members_ok):
                    model.Add(x[gid, hk] == 0)

        # ── Constraint 5: Special needs ──────────────────────────────
        # Children with special needs must go to homes that accept them.
        for ck in child_keys:
            c_obj = next(c for c in children if c.key == ck)
            if c_obj.special_needs:
                for hk in home_keys:
                    h_obj = next(h for h in homes if h.key == hk)
                    if not h_obj.accepts_special_needs:
                        model.Add(y[ck, hk] == 0)
                for gid in group_ids:
                    if c_obj.sibling_group_id == gid:
                        for hk in home_keys:
                            h_obj = next(h for h in homes if h.key == hk)
                            if not h_obj.accepts_special_needs:
                                model.Add(x[gid, hk] == 0)

        # ── Constraint 6: Court-ordered separation ───────────────────
        # Certain child pairs may not share a home.
        for ci, cj in constraints.court_separations:
            for hk in home_keys:
                model.Add(y.get((ci, hk), 0) + y.get((cj, hk), 0) <= 1)
                # Also forbid them being co-placed via whole-group vars
                # Find which groups they belong to
                gi = next((gid for gid in group_ids
                          if ci in [c.key for c in groups[gid]]), None)
                gj = next((gid for gid in group_ids
                          if cj in [c.key for c in groups[gid]]), None)
                if gi and gj and gi == gj:
                    # Both in same group — forbid whole-group placement
                    model.Add(x[gi, hk] == 0)

        # ── Constraint 7: Geographic split bound ─────────────────────
        # If a sibling group is split across two homes, those homes
        # must be within max_split_km of each other.  If the road
        # distance exceeds the limit, the solver is forbidden from
        # assigning the group to both homes simultaneously.
        #
        # The v[gid, fi, fj] variable tracks whether group gid is
        # placed in both fi AND fj (i.e. it is split across them).
        # This is used in the objective to penalise split distance.
        v: dict[tuple[str, str, str], cp_model.IntVar] = {}
        for gid in group_ids:
            for fi, fj in itertools.combinations(home_keys, 2):
                v[gid, fi, fj] = model.NewBoolVar(f"v_{gid}_{fi}_{fj}")
                # v = 1 if both x[gid, fi] AND x[gid, fj] are 1
                model.Add(v[gid, fi, fj] >= x[gid, fi] + x[gid, fj] - 1)
                model.Add(v[gid, fi, fj] <= x[gid, fi])
                model.Add(v[gid, fi, fj] <= x[gid, fj])

                # Hard bound: if distance > max_split_km, forbid co-assignment
                h_i = next(h for h in homes if h.key == fi)
                h_j = next(h for h in homes if h.key == fj)
                dist = road_distance_km(h_i, h_j)
                if dist > constraints.max_split_km:
                    model.Add(x[gid, fi] + x[gid, fj] <= 1)

        # ── Constraint 8 (soft): same caseworker for split groups ───
        # We'll add a penalty term in the objective instead of a hard
        # constraint (rural counties may have 1 caseworker).

        # ── Objective ────────────────────────────────────────────────
        # Term 1: Reward co-placement weighted by trauma score.
        # Groups that experienced the same removal incident get a high
        # co-placement bonus; the solver will only split them when
        # capacity constraints leave no alternative.
        term1 = sum(
            group_trauma[gid] * u[gid] * self.alpha[1]
            for gid in group_ids
        )

        # Term 2: Reward stability for individual (split) placements.
        term2 = sum(
            match_score.get((ck, hk), 0.5) * y[ck, hk] * self.alpha[2]
            for ck in child_keys for hk in home_keys
        )

        # Term 3: Reward trauma-informed match for whole-group placements.
        # Scaled by group size so it is comparable to term 2 when the
        # alternative is splitting the group.
        term3 = sum(
            match_score.get((groups[gid][0].key, hk), 0.5)
            * x[gid, hk] * group_sizes[gid] * self.alpha[3]
            for gid in group_ids for hk in home_keys
        )

        # Term 4: Penalise school distance (placeholder — requires
        # geocoded school addresses linked to each child).
        term4 = 0

        # Term 5: Penalise every pair of homes involved in a split,
        # whether via whole-group x variables (tracked by v) or
        # individual y variables.  Distance-weighted so nearby
        # splits are preferred over long-distance ones.
        term5_components: list[cp_model.IntVar | int] = []
        for gid in group_ids:
            members = [c.key for c in groups[gid]]
            for fi, fj in itertools.combinations(home_keys, 2):
                h_i = next(h for h in homes if h.key == fi)
                h_j = next(h for h in homes if h.key == fj)
                dist = road_distance_km(h_i, h_j)
                # Indicator: at least one child from this group in fi AND
                # at least one in fj (group is split across this pair)
                any_fi = model.NewBoolVar(f"cf_{gid}_{fi}")
                any_fj = model.NewBoolVar(f"cf_{gid}_{fj}")
                split_pair = model.NewBoolVar(f"sp_{gid}_{fi}_{fj}")
                model.Add(any_fi >= x[gid, fi]).OnlyEnforceIf(x[gid, fi])
                model.AddMaxEquality(any_fi, [x[gid, fi]] + [y[ck, fi] for ck in members])
                model.AddMaxEquality(any_fj, [x[gid, fj]] + [y[ck, fj] for ck in members])
                model.Add(split_pair >= any_fi + any_fj - 1)
                term5_components.append(
                    int(round(dist * self.alpha[5])) * split_pair
                )
        term5 = -sum(term5_components)

        # Term 6: Penalise cross-caseworker splits (soft constraint).
        # Rural counties with a single caseworker are not penalised;
        # urban counties with many caseworkers avoid splits across workers.
        cw_penalties: list[cp_model.IntVar | int] = []
        for gid in group_ids:
            fi_homes = list(home_keys)
            for fi, fj in itertools.combinations(fi_homes, 2):
                h_i = next(h for h in homes if h.key == fi)
                h_j = next(h for h in homes if h.key == fj)
                if h_i.caseworker_id != h_j.caseworker_id:
                    cw_mix = model.NewBoolVar(f"cw_{gid}_{fi}_{fj}")
                    any_fi = model.NewBoolVar(f"cwa_{gid}_{fi}")
                    any_fj = model.NewBoolVar(f"cwb_{gid}_{fj}")
                    model.AddMaxEquality(any_fi, [x[gid, fi]] + [y[ck, fi] for ck in [c.key for c in groups[gid]]])
                    model.AddMaxEquality(any_fj, [x[gid, fj]] + [y[ck, fj] for ck in [c.key for c in groups[gid]]])
                    model.Add(cw_mix >= any_fi + any_fj - 1)
                    cw_penalties.append(int(self.alpha[6]) * cw_mix)
        term6 = -sum(cw_penalties)

        model.Maximize(term1 + term2 + term3 + term4 + term5 + term6)

        # ── Forbid previous solutions ────────────────────────────────
        if forbid_assignment:
            for prev in forbid_assignment:
                # Build a Boolean clause that is SAT only if at least one
                # assignment differs from the forbidden one.
                literals: list[cp_model.IntVar] = []
                for ck, hk in prev.items():
                    # Find the variable that was set
                    child = next(c for c in children if c.key == ck)
                    gid = child.sibling_group_id
                    # Check if this child was placed via x (whole-group) or y (split)
                    # We add a variable that tracks whether this child's assignment
                    # matches the forbidden one.
                    var = model.NewBoolVar(f"forbid_{ck}_{hk}")
                    # var = 1 if child IS in this forbidden home
                    # We'll use x or y depending
                    in_group = all(
                        prev.get(m.key) == hk
                        for m in groups[gid]
                    )
                    if in_group:
                        model.Add(var >= x[gid, hk])
                    else:
                        model.Add(var >= y[ck, hk])
                    literals.append(var)
                # At least one variable must differ → not all literals can be 1
                model.Add(sum(literals) <= len(literals) - 1)

        # ── Solve ────────────────────────────────────────────────────
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = SOLVER_TIMEOUT_S
        solver.parameters.num_search_workers = 8
        status = solver.Solve(model)

        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None

        # ── Extract assignment ───────────────────────────────────────
        assignment: dict[str, str] = {}
        group_status: dict[str, str] = {}

        for gid in group_ids:
            assigned_home = None
            for hk in home_keys:
                if solver.Value(x[gid, hk]):
                    assigned_home = hk
                    break
            if assigned_home:
                for c in groups[gid]:
                    assignment[c.key] = assigned_home
                group_status[gid] = "together"
            else:
                # Split — find individual assignments
                cw_set: set[str] = set()
                for c in groups[gid]:
                    for hk in home_keys:
                        if solver.Value(y[c.key, hk]):
                            assignment[c.key] = hk
                            assigned_home_obj = next(h for h in homes if h.key == hk)
                            cw_set.add(assigned_home_obj.caseworker_id)
                            break
                if len(cw_set) <= 1:
                    group_status[gid] = "split"
                else:
                    group_status[gid] = "split_across_cw"

        # Ensure every child has an assignment (fill missing — should not happen)
        for c in children:
            if c.key not in assignment:
                group_status[c.sibling_group_id] = "unplaced"

        # ── Compute score breakdown ──────────────────────────────────
        score = self._compute_scores(
            assignment, children, homes, groups, group_ids, home_keys,
            match_score,
        )

        return PlacementOption(
            assignment=assignment,
            score=score,
            group_status=group_status,
        )

    # ── Score computation ────────────────────────────────────────────────

    def _compute_scores(
        self,
        assignment: dict[str, str],
        children: list[Child],
        homes: list[FosterHome],
        groups: dict[str, list[Child]],
        group_ids: list[str],
        home_keys: list[str],
        match_score: dict[tuple[str, str], float],
    ) -> ScoreBreakdown:
        """Recompute sub-scores for a given assignment (no solver needed)."""
        s = ScoreBreakdown()

        home_map = {h.key: h for h in homes}
        child_map = {c.key: c for c in children}

        # Co-placement score
        for gid in group_ids:
            members = groups[gid]
            home_ids = {assignment.get(c.key) for c in members if c.key in assignment}
            if len(home_ids) == 1 and None not in home_ids:
                # All together
                s.co_placement += max(c.trauma_score for c in members)
            elif len(home_ids) > 1:
                # Split — penalise inversely proportional to trauma
                trauma = max(c.trauma_score for c in members)
                s.co_placement += trauma * 0.2  # heavily discounted

        # Trauma match
        for gid in group_ids:
            for c in groups[gid]:
                hk = assignment.get(c.key)
                if hk:
                    ms = match_score.get((c.key, hk), 0.5)
                    s.trauma_match += ms

        # Stability (proxy: average match score per placement)
        placed = [c for c in children if c.key in assignment]
        if placed:
            s.stability = sum(
                match_score.get((c.key, assignment[c.key]), 0.5)
                for c in placed
            ) / len(placed)

        # School proximity: 0 placeholder (requires school geocoding)
        s.school_proximity = 0.0

        # Split distance penalty (lower is better → normalise to 0..1)
        total_split_dist = 0.0
        n_split = 0
        for gid in group_ids:
            members = groups[gid]
            home_ids = list({assignment.get(c.key) for c in members if c.key in assignment})
            if len(home_ids) > 1 and None not in home_ids:
                n_split += 1
                for fi, fj in itertools.combinations(home_ids, 2):
                    if fi in home_map and fj in home_map:
                        total_split_dist += road_distance_km(home_map[fi], home_map[fj])
        s.split_distance = round(total_split_dist / max(n_split, 1), 1)

        # Same-caseworker cohesion
        total_groups = len(group_ids)
        same_cw = 0
        for gid in group_ids:
            members = groups[gid]
            cw_set = set()
            for c in members:
                hk = assignment.get(c.key)
                if hk and hk in home_map:
                    cw_set.add(home_map[hk].caseworker_id)
            if len(cw_set) <= 1:
                same_cw += 1
        s.caseworker_cohesion = same_cw / max(total_groups, 1)

        # Total (weighted)
        s.total = (
            self.alpha[1] * s.co_placement +
            self.alpha[2] * s.stability +
            self.alpha[3] * s.trauma_match +
            self.alpha[4] * s.school_proximity -
            self.alpha[5] * s.split_distance / 100.0 +  # normalise
            self.alpha[6] * s.caseworker_cohesion
        )
        return s

    # ── Infeasibility diagnosis ───────────────────────────────────────

    def _diagnose_infeasibility(
        self,
        children: list[Child],
        homes: list[FosterHome],
        groups: dict[str, list[Child]],
        constraints: Constraints,
    ) -> str:
        """
        Walk through common infeasibility causes and return a human-readable
        explanation so the caseworker knows why no assignment is possible.
        """
        reasons: list[str] = []

        # Check total capacity
        total_children = len(children)
        total_beds = sum(h.available_beds for h in homes)
        if total_children > total_beds:
            reasons.append(
                f"{total_children} children but only {total_beds} available beds "
                f"across {len(homes)} homes ({total_children - total_beds} more beds needed)."
            )

        # Check age-range gaps
        unserved_age: list[str] = []
        for c in children:
            age_ok_homes = [
                h for h in homes
                if h.age_min <= c.age <= h.age_max
            ]
            if not age_ok_homes:
                unserved_age.append(f"{c.child_id} (age {c.age})")
        if unserved_age:
            reasons.append(
                f"No home accepts the age of {len(unserved_age)} child(ren): "
                f"{', '.join(unserved_age[:5])}"
            )

        # Check special-needs homes
        sn_children = [c for c in children if c.special_needs]
        sn_capable_homes = [h for h in homes if h.accepts_special_needs]
        if sn_children and not sn_capable_homes:
            reasons.append(
                f"{len(sn_children)} child(ren) with special needs but zero homes "
                f"accept special-needs placements."
            )
        elif sn_children and len(sn_children) > sum(h.available_beds for h in sn_capable_homes):
            reasons.append(
                f"Special-needs children ({len(sn_children)}) exceed available "
                f"beds in SN-capable homes "
                f"({sum(h.available_beds for h in sn_capable_homes)})."
            )

        # Check court-ordered separations vs. group co-placement
        court_pairs = set()
        for ci, cj in constraints.court_separations:
            pair = tuple(sorted([ci, cj]))
            court_pairs.add(pair)
            # Find groups
            gi = next((gid for gid, members in groups.items()
                      if ci in [m.key for m in members]), None)
            gj = next((gid for gid, members in groups.items()
                      if cj in [m.key for m in members]), None)
            if gi and gj and gi == gj:
                group_members = [m.key for m in groups[gi]]
                reasons.append(
                    f"Court orders separation of {ci} and {cj}, but both are "
                    f"in sibling group {gi} ({len(group_members)} children). "
                    f"The solver cannot place the whole group together, and "
                    f"splitting requires a second home within {constraints.max_split_km} km."
                )

        if not reasons:
            reasons.append(
                "The solver could not find a feasible placement. "
                "Possible causes: all homes within geographic range are at capacity, "
                "age-range constraints conflict with group composition, or "
                "court-ordered separations cannot be satisfied given the available homes."
            )

        return " ".join(reasons)


# ── CLI demo / smoke test ─────────────────────────────────────────────────────

if __name__ == "__main__":
    # Small test case to verify the solver works end-to-end
    sample_children = [
        Child("C001", "G1", 8, "F", False, 0.95),
        Child("C002", "G1", 6, "M", False, 0.95),
        Child("C003", "G1", 4, "F", False, 0.95),
        Child("C004", "G2", 14, "M", True,  0.6),
        Child("C005", "G2", 12, "F", False, 0.6),
    ]
    # H01: large, trauma-trained — ideal for the high-trauma sibling group G1
    # H02: small, no trauma training, limited age range — poor match for G1
    # H03: medium, trauma-trained but already 1 occupied bed, different caseworker
    sample_homes = [
        FosterHome("H01", "Johnson Home", 40.0, -89.0, 4, 0, 0, 17, True, "CW1",
                   has_trauma_training=True, has_sibling_experience=True),
        FosterHome("H02", "Williams Home", 40.1, -89.2, 2, 0, 0, 10, False, "CW1"),
        FosterHome("H03", "Smith Home", 41.0, -88.0, 2, 0, 5, 17, True, "CW2",
                   has_trauma_training=True),
    ]
    sample_constraints = Constraints(
        court_separations=[],
        max_split_km=50,
    )

    opt = SiblingPlacementOptimizer()
    result = opt.optimize(sample_children, sample_homes, sample_constraints)

    print(f"Solver status: {result.solver_status} ({result.solve_time_ms:.0f} ms)")
    print()

    def show_option(label: str, option: PlacementOption) -> None:
        print(f"── {label} ──")
        if option.infeasible_reason:
            print(f"  INFEASIBLE: {option.infeasible_reason}")
            return
        for ck, hk in option.assignment.items():
            print(f"  {ck} → {hk}")
        print(f"  Groups: {option.group_status}")
        sc = option.score
        print(f"  Score: {sc.total:.2f}  "
              f"(co-place={sc.co_placement:.2f}, stability={sc.stability:.2f}, "
              f"trauma={sc.trauma_match:.2f}, split_dist={sc.split_distance:.1f} km, "
              f"cw_cohesion={sc.caseworker_cohesion:.2f})")
        print()

    show_option("Best", result.best)
    for i, alt in enumerate(result.alternatives, 1):
        show_option(f"Alternative {i}", alt)

    def trade_off(label: str, option: PlacementOption) -> None:
        reasons: list[str] = []
        if option.infeasible_reason:
            print(f"  {label}: INFEASIBLE — {option.infeasible_reason}")
            return
        sc = option.score
        for gid, status in option.group_status.items():
            if status == "together":
                reasons.append(f"{gid} co-placed")
            elif status == "split":
                reasons.append(f"{gid} split ({sc.split_distance:.0f} km apart)")
            elif status == "split_across_cw":
                reasons.append(f"{gid} split across caseworkers")
        cohesion = "same caseworker" if sc.caseworker_cohesion > 0.5 else "split across workers"
        reasons.append(f"trauma match {sc.trauma_match:.1f}")
        print(f"  {label}: {', '.join(reasons)} | score {sc.total:.1f}")

    print("── Trade-off explanations ──")
    trade_off("Option 1 (best)", result.best)
    for i, alt in enumerate(result.alternatives, 2):
        trade_off(f"Option {i}", alt)

    # ── Infeasibility smoke test ────────────────────────────────────
    print()
    print("── Infeasibility test ──")
    overfull_homes = [
        FosterHome("H01", "Full House", 40.0, -89.0, 1, 1, 0, 17, False, "CW1"),
    ]
    result2 = opt.optimize(sample_children, overfull_homes, sample_constraints)
    print(f"  Status: {result2.solver_status}")
    print(f"  Reason: {result2.best.infeasible_reason}")
