"""
Naval Berth Allocation — MILP Benchmark (Phase 1b)
====================================================
Time-indexed formulation — tractable for CBC.

Objective:  minimise  Ω_shift + Ω_fatigue + Ω_delay  (full objective)

Why time-indexed instead of big-M continuous?
  - Big-M formulations create dense constraint matrices; CBC's feasibility
    heuristics fail to find a starting point in reasonable time.
  - Time-indexed y[s,p,l,t] = 1 "vessel s occupies (p,l) at slot t" produces
    a sparse matrix — each constraint touches only a few variables.
  - Non-overlap is implicit: the at-most-one constraint per slot is a simple
    set-packing constraint, which CBC handles very efficiently.

Phase 1b scope (deterministic, no weather/lunch):
  - Discrete 1h slots  (coarser than GA's 0.5h — keeps variable count manageable)
  - Arrival times and stay durations from scenario (deterministic)
  - Tug capacity: aggregate per slot (no disjunctive tug scheduling)
  - Fatigue: precomputed from scheduled arrival slot (night proxy)
  - Shifting: approximated as layer-conflict penalty (not exact dynamic count)

Requirements:  pip install pulp numpy pandas

Usage:
    python MILP.py                   # single MILP run
    python MILP.py --compare         # MILP + GA side-by-side
    python MILP.py --sweep N         # N seeds → CSV
    python MILP.py --horizon 72      # default; use 48 for speed
"""

import argparse
import random
import time
import numpy as np
import pandas as pd
from collections import defaultdict

try:
    import pulp
except ImportError:
    raise ImportError("Run:  pip install pulp")


# ── Problem constants ─────────────────────────────────────────────────────────

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

INCOMPATIBLE = [frozenset({'K','P'}), frozenset({'P','L'})]
N_TUGS       = 6
ALPHA        = 10   # night fatigue multiplier
SLOT_H       = 1    # time slot size in hours (1h slots = manageable variable count)


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_night(slot):
    """True if 1h slot index falls in night window (22:00–07:00)."""
    h = slot % 24
    return h >= 22 or h <= 7

def fatigue_of(v, start_slot):
    """Fatigue incurred when vessel v starts service at given slot."""
    base = VESSEL_SPECS[v['type']]['fatigue']
    return base * (ALPHA if is_night(start_slot) else 1.0)


# ── Scenario generator ────────────────────────────────────────────────────────

def generate_scenario(horizon_h=72, seed=42):
    """
    Deterministic scenario generator.
    Returns vessels with arrival and stay in 1h slot units.
    Default horizon_h=72 (3 days) → ~10-15 vessels, solves in seconds.
    horizon_h=168 (1 week) → ~24 vessels, solves in 1-3 minutes.
    """
    random.seed(seed)
    out = []
    for vtype, info in VESSEL_SPECS.items():
        for i in range(info['count']):
            curr = random.randint(0, min(info['cycle'], horizon_h))
            while curr < horizon_h:
                stay = random.randint(*info['stay_range'])
                # Only include vessel if at least one valid start slot exists:
                # vessel must be able to start at arr and finish before horizon.
                # Valid start range: [arr, horizon - stay]
                # So we need: arr <= horizon - stay  i.e. stay <= horizon - arr
                if stay <= horizon_h - curr:
                    out.append({
                        'id':     f"{vtype}{i}_{curr}",
                        'type':   vtype,
                        'arr':    curr,
                        'stay':   stay,
                    })
                curr += info['cycle']
    return sorted(out, key=lambda v: v['arr'])


# ── MILP builder ──────────────────────────────────────────────────────────────

def build_milp(scenario, horizon_h=72, time_limit_s=300, verbose=False):
    """
    Time-indexed berth allocation MILP.

    Core variable: start[s, p, l, t] = 1 if vessel s begins service
                   at pier p, layer l, at time slot t.

    From start we derive:
      - occ[s, p, l, t]: vessel s occupies (p,l) during slot t
        (= 1 if any start[s,p,l,τ] = 1 for τ in [t-stay+1, t])
      - start_slot[s]: actual start slot (continuous aux)
      - delay[s] = start_slot[s] - arr[s]

    Non-overlap constraint: Σ_s occ[s,p,l,t] ≤ 1  for all (p,l,t)
    This is a simple set-packing constraint — very sparse, CBC-friendly.
    """

    T = horizon_h   # number of 1h slots
    prob = pulp.LpProblem("NavalBerth_TimeIndexed", pulp.LpMinimize)

    # Feasible (pier, layer) slots per vessel type
    slots = {v['id']: [(p, l)
                        for p in VESSEL_SPECS[v['type']]['assigned_piers']
                        for l in range(PIER_CONFIG[p]['layers'])]
             for v in scenario}

    # Feasible start times: [arr[s], ..., T - stay[s]]
    # Last valid start t satisfies: t + stay - 1 <= T-1  =>  t <= T - stay
    # Scenario generator guarantees arr[s] <= T - stay[s], so range is non-empty.
    start_times = {v['id']: list(range(v['arr'], T - v['stay'] + 1))
                   for v in scenario}

    # Safety check
    for v in scenario:
        if not start_times[v['id']]:
            raise ValueError(
                f"Vessel {v['id']} has no valid start slots "
                f"(arr={v['arr']}, stay={v['stay']}, T={T}). "
                f"Increase horizon."
            )

    # ── Variables ─────────────────────────────────────────────────────────────

    # start[s, p, l, t]: vessel s starts at (p,l) at slot t
    # Only create where feasible — key to keeping variable count low
    start = {}
    for v in scenario:
        sid = v['id']
        for (p, l) in slots[sid]:
            for t in start_times[sid]:
                start[sid, p, l, t] = pulp.LpVariable(
                    f"st_{sid}_{p}_{l}_{t}", cat='Binary'
                )

    # start_slot[s]: continuous aux = Σ t * start[s,p,l,t]
    # upBound = T - stay[s] (last valid start slot for this vessel)
    start_slot = {v['id']: pulp.LpVariable(f"ss_{v['id']}",
                                            lowBound=v['arr'],
                                            upBound=T - v['stay'])
                  for v in scenario}

    # delay[s] = start_slot[s] - arr[s]
    delay = {v['id']: pulp.LpVariable(f"dl_{v['id']}", lowBound=0)
             for v in scenario}

    n_start_vars = len(start)
    print(f"    Vessels: {len(scenario)}  |  "
          f"start-vars: {n_start_vars}  |  "
          f"slot-vars: {len(start_slot)}")

    # ── C1: each vessel starts exactly once ───────────────────────────────────
    for v in scenario:
        sid = v['id']
        prob += (
            pulp.lpSum(start[sid, p, l, t]
                       for (p, l) in slots[sid]
                       for t in start_times[sid]) == 1,
            f"C1_{sid}"
        )

    # ── C2: start_slot definition ─────────────────────────────────────────────
    for v in scenario:
        sid = v['id']
        prob += (
            start_slot[sid] == pulp.lpSum(
                t * start[sid, p, l, t]
                for (p, l) in slots[sid]
                for t in start_times[sid]
            ),
            f"C2_{sid}"
        )

    # ── C3: delay definition ──────────────────────────────────────────────────
    for v in scenario:
        sid = v['id']
        prob += (delay[sid] == start_slot[sid] - v['arr'], f"C3_{sid}")

    # ── C4: non-overlap — at most one vessel occupies (p,l) at each slot ──────
    # Build occupation index: occ_index[(p,l,t)] = list of (sid, p, l, tau)
    # vessel s occupies (p,l) at slot t if start[s,p,l,tau]=1
    # for any tau in [t - stay[s] + 1, t]
    occ_index = defaultdict(list)
    for v in scenario:
        sid = v['id']
        stay = v['stay']
        for (p, l) in slots[sid]:
            for tau in start_times[sid]:
                # this start covers slots tau, tau+1, ..., tau+stay-1
                for t in range(tau, min(tau + stay, T)):
                    occ_index[(p, l, t)].append((sid, p, l, tau))

    for (p, l, t), occupants in occ_index.items():
        if len(occupants) > 1:
            prob += (
                pulp.lpSum(start[sid, p2, l2, tau]
                           for (sid, p2, l2, tau) in occupants) <= 1,
                f"C4_{p}_{l}_{t}"
            )

    # ── C5: adjacent layer incompatibility ────────────────────────────────────
    # At each slot t, incompatible type pairs cannot occupy adjacent layers.
    # We enforce: for each (p, l, l+1, t) and each incompatible (vi, vj) pair:
    #   occ(vi, p, l, t) + occ(vj, p, l+1, t) <= 1
    # Build per-slot adjacency constraints efficiently using occ_index.

    adj_checked = set()
    for p, cfg in PIER_CONFIG.items():
        for l in range(cfg['layers'] - 1):
            for t in range(T):
                occ_l  = occ_index.get((p, l, t),   [])
                occ_l1 = occ_index.get((p, l+1, t), [])
                for (sid_i, _, _, tau_i) in occ_l:
                    vi = next(v for v in scenario if v['id'] == sid_i)
                    for (sid_j, _, _, tau_j) in occ_l1:
                        vj = next(v for v in scenario if v['id'] == sid_j)
                        if frozenset({vi['type'], vj['type']}) in INCOMPATIBLE:
                            key = (sid_i, sid_j, p, l, t)
                            if key not in adj_checked:
                                adj_checked.add(key)
                                prob += (
                                    start[sid_i, p, l, tau_i]
                                    + start[sid_j, p, l+1, tau_j] <= 1,
                                    f"C5_{sid_i}_{sid_j}_{p}_{l}_{t}"
                                )

    # ── C6: tug capacity per slot ─────────────────────────────────────────────
    # At arrival slot t: tugs_needed[s] * start[s,p,l,t] summed ≤ N_TUGS
    # (Only counts tug usage at the START slot — simplified model)
    start_index = defaultdict(list)   # start_index[t] = [(sid,p,l)]
    for v in scenario:
        sid = v['id']
        for (p, l) in slots[sid]:
            for t in start_times[sid]:
                start_index[t].append((sid, p, l))

    for t, arrivals in start_index.items():
        if not arrivals:
            continue
        tug_expr = pulp.lpSum(
            VESSEL_SPECS[next(v for v in scenario if v['id']==sid)['type']]['tugs']
            * start[sid, p, l, t]
            for (sid, p, l) in arrivals
        )
        prob += (tug_expr <= N_TUGS, f"C6_tugs_{t}")

    # ── C7: shifting (aggregated O(V²T) formulation) ──────────────────────────
    # shift[vi] = 1 if vi (inner layer) is blocked by any vj (outer layer)
    # whose occupation window overlaps vi's window at the same pier.
    #
    # Aggregated form — one constraint per (vi, p, l_inner, tv):
    #   shift[vi] >= start[vi,p,l_inner,tv]
    #                + Σ_{vj≠vi, tw: windows overlap} start[vj,p,l_outer,tw]
    #                - 1
    #
    # Tighter than the per-pair form: captures all blockers in one row.
    # Complexity: O(V²T) constraints vs O(V²T²) previously.

    shift = {v['id']: pulp.LpVariable(f"sh_{v['id']}", cat='Binary')
             for v in scenario}

    # Precompute blocker start-time lists keyed by (vj_id, p, l_outer)
    blocker_starts = {}
    for vj in scenario:
        vj_id = vj['id']
        for (p, l) in slots[vj_id]:
            blocker_starts[(vj_id, p, l)] = start_times[vj_id]

    shift_constraints_added = 0
    for vi in scenario:
        vi_id  = vi['id']
        stay_i = vi['stay']
        for (p, l_inner) in slots[vi_id]:
            if l_inner == 0:
                continue   # outermost layer — cannot be shifted
            for tv in start_times[vi_id]:
                vi_end = tv + stay_i

                # Collect all blocker start vars whose windows overlap [tv, vi_end)
                blocker_terms = []
                for vj in scenario:
                    vj_id  = vj['id']
                    if vj_id == vi_id:
                        continue
                    stay_j = vj['stay']
                    for l_outer in range(l_inner):
                        key = (vj_id, p, l_outer)
                        if key not in blocker_starts:
                            continue
                        for tw in blocker_starts[key]:
                            if tv < tw + stay_j and tw < vi_end:
                                blocker_terms.append(start[vj_id, p, l_outer, tw])

                if not blocker_terms:
                    continue

                prob += (
                    shift[vi_id] >= (
                        start[vi_id, p, l_inner, tv]
                        + pulp.lpSum(blocker_terms)
                        - 1
                    ),
                    f"C7_{vi_id}_{p}_{l_inner}_{tv}"
                )
                shift_constraints_added += 1

    print(f"    Shifting constraints: {shift_constraints_added}  (O(V²T), was O(V²T²))")

    # ── Objective ─────────────────────────────────────────────────────────────
    # Full objective now matches GA raw accumulators:
    #   minimise  Ω_shift + Ω_fatigue + Ω_delay
    # Weight for shifting set to 1 (raw count, matching GA's self.shifting += 1)
    # Fatigue: precomputed per (vessel, start_slot) combination
    fatigue_expr = pulp.lpSum(
        fatigue_of(v, t) * start[v['id'], p, l, t]
        for v in scenario
        for (p, l) in slots[v['id']]
        for t in start_times[v['id']]
    )

    delay_expr   = pulp.lpSum(delay[v['id']] for v in scenario)
    shift_expr   = pulp.lpSum(shift[v['id']] for v in scenario)

    prob += (shift_expr + fatigue_expr + delay_expr, "Objective")

    # ── Solve ─────────────────────────────────────────────────────────────────
    solver = pulp.PULP_CBC_CMD(
        msg       = 1 if verbose else 0,
        timeLimit = time_limit_s,
        gapRel    = 0.05,
        threads   = 4,
    )

    t0 = time.time()
    prob.solve(solver)
    solve_time = time.time() - t0

    # ── Extract solution ──────────────────────────────────────────────────────
    status  = pulp.LpStatus[prob.status]
    obj_val = pulp.value(prob.objective) if prob.status in (1, -2) else None

    total_delay    = 0.0
    total_fatigue  = 0.0
    total_shifting = 0
    assignments    = []

    if prob.status in (1, -2):
        for v in scenario:
            sid = v['id']
            pier, layer, start_t = None, None, None
            for (p, l) in slots[sid]:
                for t in start_times[sid]:
                    val = pulp.value(start[sid, p, l, t])
                    if val is not None and val > 0.5:
                        pier, layer, start_t = p, l, t
                        break
                if start_t is not None:
                    break

            if start_t is not None:
                dly  = max(0.0, start_t - v['arr'])
                fat  = fatigue_of(v, start_t)
                shft = round(pulp.value(shift[sid]) or 0)
                total_delay    += dly
                total_fatigue  += fat
                total_shifting += shft
                assignments.append({
                    'id':         sid,
                    'type':       v['type'],
                    'pier':       pier,
                    'layer':      layer,
                    'arr_sched':  v['arr'],
                    'arr_actual': start_t,
                    'dep_actual': start_t + v['stay'],
                    'delay':      round(dly, 2),
                    'fatigue':    round(fat, 2),
                    'shifting':   shft,
                })

    return {
        'status':        status,
        'obj_value':     round(obj_val, 3) if obj_val is not None else None,
        'shifting':      total_shifting,
        'fatigue':       round(total_fatigue, 2),
        'delay':         round(total_delay, 2),
        'assignments':   assignments,
        'solve_time_s':  round(solve_time, 2),
        'n_vessels':     len(scenario),
        'n_vars':        prob.numVariables(),
        'n_constraints': prob.numConstraints(),
    }


# ── GA runner ─────────────────────────────────────────────────────────────────

def run_ga_on_scenario(scenario, horizon_h=168):
    """
    Run GA and FCFS on the MILP's filtered scenario.
    Both solvers use the same vessel set and the same horizon cap.
    Tick conversion: MILP 1h slots x2 = GA ticks.
    Delay is accumulated in 0.5h steps by GA so divide by 2 for hours.
    """
    try:
        from Naval_sim_core import NavalFinalOptimizer
    except ImportError:
        try:
            from Batch_Allocation import NavalFinalOptimizer
        except ImportError:
            print("  [Warning] No GA file found — skipping GA comparison.")
            return None

    ga_scen = sorted([{
        'id':       v['id'],
        'type':     v['type'],
        'arr':      v['arr'] * 2,       # hours -> ticks
        'arr_orig': v['arr'] * 2,
        'stay':     v['stay'],          # hours (GA doubles internally)
    } for v in scenario], key=lambda v: v['arr'])

    results = {}
    for mode in ('GA', 'FCFS'):
        sim = NavalFinalOptimizer(ga_scen, mode=mode, record_log=False)
        res = sim.run(max_h=horizon_h)  # cap to MILP horizon
        results[mode] = {
            'shifting': res['shifting'],
            'fatigue':  res['fatigue'],
            'delay':    res['delay'] / 2,  # ticks -> hours
        }
    return results


# ── Run modes ─────────────────────────────────────────────────────────────────

def compare_single(horizon_h=72, seed=42, verbose=False, time_limit_s=300):
    print(f"\n{'='*65}")
    print(f"  Naval Berth Allocation — MILP vs GA Benchmark")
    print(f"  Horizon: {horizon_h}h  |  Seed: {seed}")
    print(f"{'='*65}")

    scenario = generate_scenario(horizon_h=horizon_h, seed=seed)
    counts = {}
    for v in scenario:
        counts[v['type']] = counts.get(v['type'], 0) + 1
    print(f"\n  Vessels: {len(scenario)}  —  " +
          "  ".join(f"{t}:{c}" for t, c in sorted(counts.items())))

    print(f"\n  Building time-indexed MILP...")
    milp = build_milp(scenario, horizon_h=horizon_h,
                      time_limit_s=time_limit_s, verbose=verbose)

    print(f"\n  MILP Results:")
    print(f"    Status:       {milp['status']}")
    print(f"    Solve time:   {milp['solve_time_s']}s")
    print(f"    Variables:    {milp['n_vars']}")
    print(f"    Constraints:  {milp['n_constraints']}")
    print(f"    Objective:    {milp['obj_value']}")
    print(f"    ├─ Shifting:  {milp['shifting']}")
    print(f"    ├─ Fatigue:   {milp['fatigue']}")
    print(f"    └─ Delay:     {milp['delay']}h")

    print(f"\n  Running GA and FCFS on same scenario (horizon={horizon_h}h)...")
    ga_results = run_ga_on_scenario(scenario, horizon_h=horizon_h)

    if ga_results and milp['obj_value'] is not None:
        print(f"\n  {'Metric':<14} {'MILP':>10} {'GA':>10} {'FCFS':>10}")
        print(f"  {'─'*48}")

        for metric in ('shifting', 'fatigue', 'delay'):
            milp_val = milp.get(metric, 0)
            ga_val   = ga_results['GA'][metric]
            fcfs_val = ga_results['FCFS'][metric]
            unit = 'h' if metric == 'delay' else ''
            print(f"  {metric:<14} {milp_val:>9.1f}  {ga_val:>9.1f}  {fcfs_val:>9.1f}{unit}")

        # Full objective comparison: shifting + fatigue + delay
        milp_obj = milp['obj_value']
        ga_obj   = (ga_results['GA']['shifting']
                    + ga_results['GA']['fatigue']
                    + ga_results['GA']['delay'])
        fcfs_obj = (ga_results['FCFS']['shifting']
                    + ga_results['FCFS']['fatigue']
                    + ga_results['FCFS']['delay'])
        gap_ga   = (ga_obj   - milp_obj) / milp_obj * 100
        gap_fcfs = (fcfs_obj - milp_obj) / milp_obj * 100

        print(f"\n  Combined (shift + fatigue + delay):")
        print(f"    MILP:  {milp_obj:.1f}")
        print(f"    GA:    {ga_obj:.1f}  (gap vs MILP: {gap_ga:+.1f}%)")
        print(f"    FCFS:  {fcfs_obj:.1f}  (gap vs MILP: {gap_fcfs:+.1f}%)")
        print(f"\n  {'─'*40}")
        print(f"  GA improvement over FCFS: {(fcfs_obj-ga_obj)/fcfs_obj*100:+.1f}%")
        print(f"  {'─'*40}")
    elif milp['obj_value'] is None:
        print(f"\n  [!] MILP did not find a solution. Try --horizon 48.")

    if milp['assignments']:
        print(f"\n  Assignment Schedule (MILP):")
        print(f"  {'ID':<20} {'Type'} {'Pier':<5} {'Lyr'} "
              f"{'Arr':>5} {'Dep':>5} {'Dly':>5} {'Fat':>6} {'Sft':>4}")
        print(f"  {'-'*65}")
        for row in sorted(milp['assignments'], key=lambda r: r['arr_actual']):
            print(f"  {row['id']:<20} {row['type']:<4}  {str(row['pier']):<5} "
                  f"{str(row['layer']):<4} {row['arr_actual']:>5} "
                  f"{row['dep_actual']:>5} {row['delay']:>5.1f} "
                  f"{row['fatigue']:>6.1f} {row['shifting']:>4}")

    return milp, ga_results


def sweep_comparison(n=10, horizon_h=72, time_limit_s=300):
    print(f"\nSweep: {n} instances  |  Horizon: {horizon_h}h")
    print(f"{'Seed':<6} {'MILP':>8} {'GA':>8} {'FCFS':>9} "
          f"{'GA gap':>7} {'FCFS gap':>8} {'GA>FCFS':>8} {'Time':>6}")
    print("─" * 72)

    rows = []
    for seed in range(n):
        scenario   = generate_scenario(horizon_h=horizon_h, seed=seed)
        milp       = build_milp(scenario, horizon_h=horizon_h,
                                time_limit_s=time_limit_s, verbose=False)
        ga_results = run_ga_on_scenario(scenario, horizon_h=horizon_h)

        milp_obj  = milp['obj_value'] or float('nan')
        ga_obj    = (ga_results['GA']['shifting']   + ga_results['GA']['fatigue']   + ga_results['GA']['delay'])   if ga_results else float('nan')
        fcfs_obj  = (ga_results['FCFS']['shifting'] + ga_results['FCFS']['fatigue'] + ga_results['FCFS']['delay']) if ga_results else float('nan')
        gap_ga    = ((ga_obj   - milp_obj) / milp_obj * 100 if milp_obj and milp_obj > 0 else float('nan'))
        gap_fcfs  = ((fcfs_obj - milp_obj) / milp_obj * 100 if milp_obj and milp_obj > 0 else float('nan'))
        ga_impr   = ((fcfs_obj - ga_obj)   / fcfs_obj * 100 if fcfs_obj and fcfs_obj > 0 else float('nan'))

        print(f"{seed:<6} {milp_obj:>8.1f} {ga_obj:>8.1f} {fcfs_obj:>9.1f} "
              f"{gap_ga:>7.1f}% {gap_fcfs:>7.1f}% {ga_impr:>7.1f}%"
              f" {milp['solve_time_s']:>6.1f}s")
        rows.append({
            'seed': seed, 'n_vessels': milp['n_vessels'],
            'milp_obj': milp_obj, 'ga_obj': ga_obj, 'fcfs_obj': fcfs_obj,
            'gap_ga_pct': gap_ga, 'gap_fcfs_pct': gap_fcfs,
            'ga_impr_over_fcfs_pct': ga_impr,
            'ga_shifting':   ga_results['GA']['shifting']   if ga_results else float('nan'),
            'fcfs_shifting': ga_results['FCFS']['shifting'] if ga_results else float('nan'),
            'solve_time_s': milp['solve_time_s'], 'status': milp['status']
        })

    df = pd.DataFrame(rows)
    print(f"\nSummary (delay + fatigue, {n} instances):")
    print(f"  Mean GA gap vs MILP:    {df['gap_ga_pct'].mean():.1f}%")
    print(f"  Mean FCFS gap vs MILP:  {df['gap_fcfs_pct'].mean():.1f}%")
    print(f"  Mean GA impr over FCFS: {df['ga_impr_over_fcfs_pct'].mean():.1f}%")
    print(f"  Mean solve time:        {df['solve_time_s'].mean():.1f}s")
    df.to_csv("milp_ga_gap_sweep.csv", index=False)
    print(f"  Saved → milp_ga_gap_sweep.csv")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Naval MILP Benchmark")
    parser.add_argument('--compare',   action='store_true')
    parser.add_argument('--sweep',     type=int, default=0, metavar='N')
    parser.add_argument('--horizon',   type=int, default=72,
                        help='Hours (default 72=3 days; 168=1 week)')
    parser.add_argument('--timelimit', type=int, default=300)
    parser.add_argument('--seed',      type=int, default=42)
    parser.add_argument('--verbose',   action='store_true')
    args = parser.parse_args()

    if args.sweep > 0:
        sweep_comparison(n=args.sweep, horizon_h=args.horizon,
                         time_limit_s=args.timelimit)
    else:
        compare_single(horizon_h=args.horizon, seed=args.seed,
                       verbose=args.verbose, time_limit_s=args.timelimit)
