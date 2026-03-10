"""
Naval Berth Allocation — MILP Benchmark
====================================================
Mirrors the GA's objectives exactly:
    minimise  Ω_shift + Ω_fatigue + Ω_delay   (raw, unweighted accumulators)

Solves a deterministic, small-instance version for benchmarking against GA.

Requirements:
    pip install pulp numpy pandas

Usage:
    python naval_milp_benchmark.py              # runs single small instance
    python naval_milp_benchmark.py --compare    # runs GA vs MILP on same scenario
    python naval_milp_benchmark.py --sweep N    # runs N random instances, reports gap

Author: generated for Phase 1b
"""

import argparse
import random
import time
import numpy as np
import pandas as pd
from itertools import combinations

try:
    import pulp
except ImportError:
    raise ImportError("Run:  pip install pulp")


# ── Shared problem data (identical to GA code) ────────────────────────────────

VESSEL_SPECS = {
    'K': {'readiness': 94, 'fatigue': 8.0, 'stay_range': (72, 96),  'tugs': 2, 'duration': 2,
          'cycle': 504, 'count': 3, 'assigned_piers': ['P1','P2','P7','P8'], 'weather_limit': 2},
    'F': {'readiness': 79, 'fatigue': 4.0, 'stay_range': (96, 168), 'tugs': 1, 'duration': 1,
          'cycle': 336, 'count': 5, 'assigned_piers': ['P4','P5','P6'],      'weather_limit': 1},
    'L': {'readiness': 63, 'fatigue': 6.0, 'stay_range': (168,168), 'tugs': 2, 'duration': 2,
          'cycle': 168, 'count': 4, 'assigned_piers': ['P1','P2','P7','P8'], 'weather_limit': 1},
    'P': {'readiness': 31, 'fatigue': 1.0, 'stay_range': (96, 144), 'tugs': 1, 'duration': 1,
          'cycle': 240, 'count': 12,'assigned_piers': ['P3','P4','P5','P6'], 'weather_limit': 0},
}

PIER_CONFIG = {
    'P1': {'layers': 3}, 'P2': {'layers': 3}, 'P3': {'layers': 1},
    'P4': {'layers': 2}, 'P5': {'layers': 2}, 'P6': {'layers': 2},
    'P7': {'layers': 3}, 'P8': {'layers': 3},
}

# Incompatible adjacent-layer pairs  {type1, type2}
INCOMPATIBLE_PAIRS = [{'K', 'P'}, {'P', 'L'}]

N_TUGS   = 6    # total tugs available
ALPHA    = 10   # night fatigue multiplier
# Night window: ticks 44–47 and 0–14 of each 48-tick day
# In hours: 22:00–24:00 and 00:00–07:00


# ── Helper: night indicator (hour-space, not tick-space) ──────────────────────

def is_night_hour(h: float) -> bool:
    """True if hour h (mod 24) falls in the night window used by the GA."""
    hmod = h % 24
    return hmod >= 22 or hmod <= 7


# ── Small-instance scenario generator ─────────────────────────────────────────

def generate_small_scenario(horizon_h: int = 168, seed: int = 42) -> list[dict]:
    """
    One-week horizon, deterministic seed.
    Produces ~15–25 vessel calls — tractable for CBC.
    Returns list of dicts with keys: id, type, arr_h, stay_h
    (hours throughout, no tick doubling — MILP works in hours)
    """
    random.seed(seed)
    scenario = []
    for vtype, info in VESSEL_SPECS.items():
        for i in range(info['count']):
            # start offset within first cycle
            curr_h = random.randint(0, min(info['cycle'], horizon_h))
            while curr_h < horizon_h:
                stay = random.randint(*info['stay_range'])
                scenario.append({
                    'id':      f"{vtype}{i}_{curr_h}",
                    'type':    vtype,
                    'arr_h':   curr_h,          # earliest arrival (hours)
                    'stay_h':  stay,            # required stay (hours)
                })
                curr_h += info['cycle']
    scenario.sort(key=lambda v: v['arr_h'])
    return scenario


# ── Night-window fatigue parameter pre-computation ────────────────────────────

def compute_night_fatigue(vessel: dict, T_max_h: int) -> float:
    """
    Because we treat actual arrival time a[v] as a continuous variable,
    we approximate the fatigue for the MILP using:
        - if the vessel's earliest arrival hour is in a night window → use α multiplier
        - otherwise → base rate
    This is a conservative linearisation; Phase 2+ can add binary night variables.
    """
    h = vessel['arr_h']
    base = VESSEL_SPECS[vessel['type']]['fatigue']
    return base * (ALPHA if is_night_hour(h) else 1.0)


# ── Core MILP builder ─────────────────────────────────────────────────────────

def build_milp(scenario: list[dict],
               horizon_h: int = 168,
               tug_aggregate: bool = True,
               time_limit_s: int = 120,
               verbose: bool = False) -> dict:
    """
    Build and solve the MILP.

    Simplifications active for Phase 1b
    (flags to relax in later phases):
        tug_aggregate=True   →  aggregate tug constraint (≤ N_TUGS/2 ops per 2h slot)
                                 instead of full disjunctive tug scheduling.
                                 Set False for exact tug model (much slower).

    Returns dict with keys:
        status, obj_value, shifting, fatigue, delay,
        assignments (list of dicts), solve_time_s
    """

    prob = pulp.LpProblem("NavalBerthAllocation", pulp.LpMinimize)
    M    = horizon_h * 10   # big-M, safely larger than any time value

    vessels = scenario
    V       = [v['id'] for v in vessels]
    vdict   = {v['id']: v for v in vessels}

    # enumerate valid (pier, layer) slots per vessel
    slots = {}   # slots[vid] = list of (pier, layer) pairs
    for v in vessels:
        ap = VESSEL_SPECS[v['type']]['assigned_piers']
        slots[v['id']] = [
            (p, l)
            for p in ap
            for l in range(PIER_CONFIG[p]['layers'])
        ]

    # ── Decision variables ────────────────────────────────────────────────────

    # x[v, p, l] — assignment binary
    x = {
        (v['id'], p, l): pulp.LpVariable(f"x_{v['id']}_{p}_{l}", cat='Binary')
        for v in vessels
        for (p, l) in slots[v['id']]
    }

    # a[v] — actual arrival time (hours), continuous
    a = {
        v['id']: pulp.LpVariable(f"a_{v['id']}", lowBound=vdict[v['id']]['arr_h'])
        for v in vessels
    }

    # d[v] — departure time = a[v] + stay_v  (derived, but explicit for constraints)
    d = {
        v['id']: pulp.LpVariable(f"d_{v['id']}", lowBound=0)
        for v in vessels
    }

    # delta[v] — arrival delay
    delta = {
        v['id']: pulp.LpVariable(f"delta_{v['id']}", lowBound=0)
        for v in vessels
    }

    # s[v] — shifting binary (1 if vessel ever blocked at departure)
    s = {
        v['id']: pulp.LpVariable(f"s_{v['id']}", cat='Binary')
        for v in vessels
    }

    # o[v, v'] — ordering binary for non-overlap disjunction
    # o=1 means v departs before v' arrives (at the same berth slot)
    pairs = []
    for (vi, vj) in combinations(V, 2):
        # only need ordering var if they share at least one feasible slot
        shared = set(slots[vi]) & set(slots[vj])
        if shared:
            pairs.append((vi, vj))

    o = {
        (vi, vj): pulp.LpVariable(f"o_{vi}_{vj}", cat='Binary')
        for (vi, vj) in pairs
    }

    # ── Constraints ───────────────────────────────────────────────────────────

    # C1: each vessel assigned exactly one slot
    for v in vessels:
        prob += (
            pulp.lpSum(x[v['id'], p, l] for (p, l) in slots[v['id']]) == 1,
            f"C1_assign_{v['id']}"
        )

    # C2: departure time definition
    for v in vessels:
        prob += (d[v['id']] == a[v['id']] + v['stay_h'],  f"C2_dep_{v['id']}")

    # C3: delay definition
    for v in vessels:
        prob += (delta[v['id']] == a[v['id']] - v['arr_h'],  f"C3_delay_{v['id']}")

    # C4: no-overlap at same (p, l) — disjunctive big-M
    for (vi, vj) in pairs:
        shared = set(slots[vi]) & set(slots[vj])
        for (p, l) in shared:
            xvi = x[vi, p, l]
            xvj = x[vj, p, l]
            ov  = o[vi, vj]

            # if both assigned here → one must depart before other arrives
            # d[vi] ≤ a[vj]  OR  d[vj] ≤ a[vi]
            prob += (
                d[vi] <= a[vj] + M * ov + M * (1 - xvi) + M * (1 - xvj),
                f"C4a_nooverlap_{vi}_{vj}_{p}_{l}"
            )
            prob += (
                d[vj] <= a[vi] + M * (1 - ov) + M * (1 - xvi) + M * (1 - xvj),
                f"C4b_nooverlap_{vi}_{vj}_{p}_{l}"
            )

    # C5: adjacent layer type incompatibility (static elimination)
    for p in PIER_CONFIG:
        n_layers = PIER_CONFIG[p]['layers']
        for l in range(n_layers - 1):
            for vi in vessels:
                for vj in vessels:
                    if vi['id'] == vj['id']:
                        continue
                    pair = {vi['type'], vj['type']}
                    if pair in INCOMPATIBLE_PAIRS:
                        # vi at layer l, vj at layer l+1 (or vice versa) → forbidden
                        if (p, l) in slots[vi['id']] and (p, l+1) in slots[vj['id']]:
                            prob += (
                                x[vi['id'], p, l] + x[vj['id'], p, l+1] <= 1,
                                f"C5_incompat_{vi['id']}_{vj['id']}_{p}_{l}"
                            )

    # C6: shifting — triggered when inner vessel (l>0) departs while outer layer occupied
    # s[v] ≥ x[v,p,l] + x[v',p,l'] - 1  for all l' < l, if stays overlap at d[v]
    # We use a linearised overlap indicator:
    #   overlap[v,v'] = 1 if their berth windows intersect
    # Approximation: if a[v'] ≤ d[v] AND a[v] ≤ d[v'], windows overlap
    # We enforce this via auxiliary binary ov_shift[v,v'] capturing temporal overlap.

    ov_shift = {}
    for vi in vessels:
        for vj in vessels:
            if vi['id'] >= vj['id']:
                continue
            key = (vi['id'], vj['id'])
            ov_shift[key] = pulp.LpVariable(f"ovs_{vi['id']}_{vj['id']}", cat='Binary')

            # ov_shift = 1 if windows overlap: a[vi] < d[vj] AND a[vj] < d[vi]
            # Linearisation:
            #   a[vi] < d[vj]  ↔  d[vj] - a[vi] ≥ ε  → d[vj] - a[vi] ≥ 1 - M(1-ov_shift)
            #   a[vj] < d[vi]  ↔  d[vi] - a[vj] ≥ 1 - M(1-ov_shift)
            eps = 0.5  # half-hour minimum overlap to count
            prob += (
                d[vj['id']] - a[vi['id']] >= eps - M * (1 - ov_shift[key]),
                f"C6_ovs_a_{vi['id']}_{vj['id']}"
            )
            prob += (
                d[vi['id']] - a[vj['id']] >= eps - M * (1 - ov_shift[key]),
                f"C6_ovs_b_{vi['id']}_{vj['id']}"
            )

    for vi in vessels:
        for vj in vessels:
            if vi['id'] == vj['id']:
                continue
            key = tuple(sorted([vi['id'], vj['id']]))
            if key not in ov_shift:
                continue
            for p in PIER_CONFIG:
                n_layers = PIER_CONFIG[p]['layers']
                for l_inner in range(1, n_layers):       # vi is in inner layer
                    for l_outer in range(l_inner):       # vj is in blocking outer layer
                        if (p, l_inner) not in slots[vi['id']]:
                            continue
                        if (p, l_outer) not in slots[vj['id']]:
                            continue
                        # s[vi] ≥ x[vi,p,l_inner] + x[vj,p,l_outer] + ov_shift - 2
                        prob += (
                            s[vi['id']] >= (
                                x[vi['id'], p, l_inner]
                                + x[vj['id'], p, l_outer]
                                + ov_shift[key]
                                - 2
                            ),
                            f"C6_shift_{vi['id']}_{vj['id']}_{p}_{l_inner}_{l_outer}"
                        )

    # C7: tug availability
    if tug_aggregate:
        # Aggregate: in any 2-hour window, total tug-operations ≤ floor(N_TUGS / max_tugs_per_op)
        # We bucket arrivals into 2h slots and cap simultaneous operations.
        # This is a relaxation of the exact disjunctive tug model.
        slot_duration = 2   # hours
        n_slots = int(np.ceil(horizon_h / slot_duration))
        for ts in range(n_slots):
            t_lo = ts * slot_duration
            t_hi = t_lo + slot_duration
            # vessels that could arrive in this slot
            candidates = [v for v in vessels if v['arr_h'] < t_hi]
            if not candidates:
                continue

            # sum of tugs × x[v,p,l] for vessels arriving in [t_lo, t_hi]
            # (we can't directly bound a[v] to a slot without more binaries,
            #  so we use arr_h as a proxy — conservative)
            slot_vessels = [v for v in vessels
                            if t_lo <= v['arr_h'] < t_hi]
            if not slot_vessels:
                continue

            tug_expr = pulp.lpSum(
                VESSEL_SPECS[v['type']]['tugs'] * x[v['id'], p, l]
                for v in slot_vessels
                for (p, l) in slots[v['id']]
            )
            prob += (tug_expr <= N_TUGS, f"C7_tugs_slot_{ts}")
    else:
        # Exact disjunctive tug model
        # For each pair (vi, vj) that might share a tug:
        # a[vj] ≥ a[vi] + dur_vi  OR  a[vi] ≥ a[vj] + dur_vj
        # (if both need ≥ 1 tug and G_vi + G_vj > N_TUGS)
        tug_order = {}
        for (vi, vj) in combinations(vessels, 2):
            gi = VESSEL_SPECS[vi['type']]['tugs']
            gj = VESSEL_SPECS[vj['type']]['tugs']
            if gi + gj > N_TUGS:
                key = (vi['id'], vj['id'])
                tug_order[key] = pulp.LpVariable(f"to_{vi['id']}_{vj['id']}", cat='Binary')
                di_dur = VESSEL_SPECS[vi['type']]['duration']
                dj_dur = VESSEL_SPECS[vj['type']]['duration']
                tv = tug_order[key]
                prob += (
                    a[vj['id']] >= a[vi['id']] + di_dur - M * tv,
                    f"C7_tug_a_{vi['id']}_{vj['id']}"
                )
                prob += (
                    a[vi['id']] >= a[vj['id']] + dj_dur - M * (1 - tv),
                    f"C7_tug_b_{vi['id']}_{vj['id']}"
                )

    # C8: horizon bounds
    for v in vessels:
        prob += (a[v['id']] <= horizon_h, f"C8_horizon_{v['id']}")

    # ── Fatigue computation ───────────────────────────────────────────────────
    # Precompute fatigue per vessel using arr_h as proxy for night detection.
    # Phase 1b simplification: fatigue is a fixed parameter, not a variable.
    fatigue_param = {v['id']: compute_night_fatigue(v, horizon_h) for v in vessels}

    # ── Objective ─────────────────────────────────────────────────────────────
    # Match GA raw accumulators exactly:
    #   Ω_shift   = Σ_v s[v]
    #   Ω_fatigue = Σ_v fatigue_param[v]  (fixed — see note below)
    #   Ω_delay   = Σ_v delta[v]
    #
    # Note on fatigue: in the GA, fatigue is incurred at the moment of arrival/
    # departure. Since the MILP solves for the full schedule at once and night
    # detection is a function of a[v] (continuous), we use a precomputed
    # approximation here. Phase 2 will add binary night variables for exactness.

    obj = (
          pulp.lpSum(s[v['id']] for v in vessels)                     # shifting
        + pulp.lpSum(fatigue_param[v['id']] for v in vessels)         # fatigue (fixed param)
        + pulp.lpSum(delta[v['id']] for v in vessels)                 # delay
    )
    prob += obj, "Objective"

    # ── Solve ─────────────────────────────────────────────────────────────────
    solver = pulp.PULP_CBC_CMD(
        msg      = 1 if verbose else 0,
        timeLimit= time_limit_s,
        gapRel   = 0.01,    # stop at 1% optimality gap
    )

    t_start = time.time()
    prob.solve(solver)
    solve_time = time.time() - t_start

    # ── Extract results ───────────────────────────────────────────────────────
    status = pulp.LpStatus[prob.status]
    obj_val = pulp.value(prob.objective) if prob.status == 1 else None

    assignments = []
    total_shifting = 0
    total_delay    = 0
    total_fatigue  = sum(fatigue_param.values())

    if prob.status in (1, -2):  # optimal or time-limit with incumbent
        for v in vessels:
            vid = v['id']
            assigned_pier, assigned_layer = None, None
            for (p, l) in slots[vid]:
                if pulp.value(x[vid, p, l]) is not None and pulp.value(x[vid, p, l]) > 0.5:
                    assigned_pier, assigned_layer = p, l
                    break
            arr_actual = pulp.value(a[vid]) or v['arr_h']
            dep_actual = pulp.value(d[vid]) or (v['arr_h'] + v['stay_h'])
            dly        = pulp.value(delta[vid]) or 0
            shft       = pulp.value(s[vid]) or 0
            total_delay    += max(0, dly)
            total_shifting += round(shft)
            assignments.append({
                'id':          vid,
                'type':        v['type'],
                'pier':        assigned_pier,
                'layer':       assigned_layer,
                'arr_sched':   v['arr_h'],
                'arr_actual':  round(arr_actual, 2),
                'dep_actual':  round(dep_actual, 2),
                'delay':       round(max(0, dly), 2),
                'shifting':    round(shft),
                'fatigue':     round(fatigue_param[vid], 2),
            })

    return {
        'status':      status,
        'obj_value':   round(obj_val, 3) if obj_val is not None else None,
        'shifting':    total_shifting,
        'fatigue':     round(total_fatigue, 2),
        'delay':       round(total_delay, 2),
        'assignments': assignments,
        'solve_time_s': round(solve_time, 2),
        'n_vessels':   len(vessels),
        'n_vars':      prob.numVariables(),
        'n_constraints': prob.numConstraints(),
    }


# ── GA runner (imported from your original code) ──────────────────────────────

def run_ga_on_scenario(scenario_h: list[dict], mode: str = 'GA') -> dict:
    """
    Convert hour-based MILP scenario back to tick-based GA scenario and run.
    Returns GA metrics aligned with MILP output format.
    """
    # Import GA code — assumes naval_ga.py is in the same directory
    # If running standalone, we inline the minimal needed logic here.
    try:
        from naval_ga import NavalFinalOptimizer  # your original file
    except ImportError:
        print("  [Warning] naval_ga.py not found — skipping GA comparison.")
        return None

    # Convert to GA tick format
    ga_scenario = []
    for v in scenario_h:
        ga_scenario.append({
            'id':       v['id'],
            'type':     v['type'],
            'arr':      v['arr_h'] * 2,       # hours → ticks
            'arr_orig': v['arr_h'] * 2,
            'stay':     v['stay_h'],           # GA stores stay in hours, doubles internally
        })
    ga_scenario.sort(key=lambda x: x['arr'])

    sim = NavalFinalOptimizer(ga_scenario, mode=mode, record_log=False)
    res = sim.run()
    return {
        'shifting':  res['shifting'],
        'fatigue':   res['fatigue'],
        'delay':     res['delay'],
    }


# ── Benchmark comparison ───────────────────────────────────────────────────────

def compare_single(horizon_h: int = 168, seed: int = 42, verbose: bool = True):
    """Run MILP and GA on the same scenario, print comparison."""
    print(f"\n{'='*65}")
    print(f"  Naval Berth Allocation — MILP vs GA Benchmark")
    print(f"  Horizon: {horizon_h}h  |  Seed: {seed}")
    print(f"{'='*65}")

    scenario = generate_small_scenario(horizon_h=horizon_h, seed=seed)
    print(f"\n  Vessels in scenario: {len(scenario)}")
    type_counts = {}
    for v in scenario:
        type_counts[v['type']] = type_counts.get(v['type'], 0) + 1
    for t, c in sorted(type_counts.items()):
        print(f"    {t}-type: {c}")

    print(f"\n  Solving MILP (CBC, 120s limit)...")
    milp = build_milp(scenario, horizon_h=horizon_h, verbose=verbose)

    print(f"\n  MILP Results:")
    print(f"    Status:       {milp['status']}")
    print(f"    Solve time:   {milp['solve_time_s']}s")
    print(f"    Variables:    {milp['n_vars']}")
    print(f"    Constraints:  {milp['n_constraints']}")
    print(f"    Objective:    {milp['obj_value']}")
    print(f"    ├─ Shifting:  {milp['shifting']}")
    print(f"    ├─ Fatigue:   {milp['fatigue']}")
    print(f"    └─ Delay:     {milp['delay']}h")

    print(f"\n  Running GA on same scenario...")
    ga = run_ga_on_scenario(scenario)
    if ga:
        ga_obj = ga['shifting'] + ga['fatigue'] + ga['delay']
        gap    = ((ga_obj - milp['obj_value']) / milp['obj_value'] * 100
                  if milp['obj_value'] and milp['obj_value'] > 0 else float('nan'))
        print(f"\n  GA Results:")
        print(f"    Objective:    {ga_obj:.2f}")
        print(f"    ├─ Shifting:  {ga['shifting']}")
        print(f"    ├─ Fatigue:   {ga['fatigue']:.2f}")
        print(f"    └─ Delay:     {ga['delay']:.2f}h")
        print(f"\n  {'─'*40}")
        print(f"  Optimality gap: {gap:.1f}%")
        print(f"  {'─'*40}")

    if milp['assignments']:
        print(f"\n  Assignment Schedule (MILP):")
        print(f"  {'ID':<18} {'Type'} {'Pier'} {'Layer'} {'Arr':>6} {'Dep':>6} "
              f"{'Delay':>6} {'Shift':>5}")
        print(f"  {'-'*65}")
        for a_row in sorted(milp['assignments'], key=lambda r: r['arr_actual']):
            print(f"  {a_row['id']:<18} {a_row['type']:<4}  "
                  f"{str(a_row['pier']):<4}  {str(a_row['layer']):<5}  "
                  f"{a_row['arr_actual']:>6.1f}  {a_row['dep_actual']:>6.1f}  "
                  f"{a_row['delay']:>6.1f}  {a_row['shifting']:>5}")

    return milp, ga


def sweep_comparison(n: int = 20, horizon_h: int = 168):
    """Run N random instances, report gap distribution."""
    print(f"\nSweep: {n} instances, horizon={horizon_h}h")
    print(f"{'Seed':<6} {'MILP obj':>10} {'GA obj':>10} {'Gap%':>8} {'Solve(s)':>9} Status")
    print("-" * 55)

    rows = []
    for seed in range(n):
        scenario = generate_small_scenario(horizon_h=horizon_h, seed=seed)
        milp     = build_milp(scenario, horizon_h=horizon_h, verbose=False)
        ga       = run_ga_on_scenario(scenario)

        milp_obj = milp['obj_value'] or float('nan')
        ga_obj   = (ga['shifting'] + ga['fatigue'] + ga['delay']) if ga else float('nan')
        gap      = ((ga_obj - milp_obj) / milp_obj * 100
                    if milp_obj and milp_obj > 0 else float('nan'))

        print(f"{seed:<6} {milp_obj:>10.2f} {ga_obj:>10.2f} {gap:>7.1f}% "
              f"{milp['solve_time_s']:>8.1f}s  {milp['status']}")
        rows.append({
            'seed': seed, 'milp_obj': milp_obj, 'ga_obj': ga_obj,
            'gap_pct': gap, 'solve_time_s': milp['solve_time_s'],
            'status': milp['status']
        })

    df = pd.DataFrame(rows)
    print(f"\nSummary ({n} instances):")
    print(f"  Mean gap:      {df['gap_pct'].mean():.1f}%")
    print(f"  Median gap:    {df['gap_pct'].median():.1f}%")
    print(f"  Max gap:       {df['gap_pct'].max():.1f}%")
    print(f"  Mean solve:    {df['solve_time_s'].mean():.1f}s")
    df.to_csv("milp_ga_gap_sweep.csv", index=False)
    print(f"  Results saved: milp_ga_gap_sweep.csv")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Naval MILP Benchmark")
    parser.add_argument('--compare', action='store_true',
                        help='Compare MILP vs GA on a single scenario')
    parser.add_argument('--sweep', type=int, default=0, metavar='N',
                        help='Run N random instances and report gap distribution')
    parser.add_argument('--horizon', type=int, default=168,
                        help='Horizon in hours (default: 168 = 1 week)')
    parser.add_argument('--seed', type=int, default=42,
                        help='Random seed for single run')
    parser.add_argument('--verbose', action='store_true',
                        help='Show CBC solver output')
    args = parser.parse_args()

    if args.sweep > 0:
        sweep_comparison(n=args.sweep, horizon_h=args.horizon)
    else:
        compare_single(horizon_h=args.horizon, seed=args.seed, verbose=args.verbose)