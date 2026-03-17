"""
Naval Berth Allocation — FastAPI Server  (Phase 2)
===================================================
Session-based FastAPI server for the Naval Berth Digital Twin.
Unity drives everything via plain HTTP (UnityWebRequest) — no WebSocket needed.

Architecture
------------
  Unity (UnityWebRequest)
        |
        | HTTP POST/GET
        v
  FastAPI server  (this file)
        |
        +---> NavalFinalOptimizer  (naval_ga.py)        stateful per-session
        +---> build_milp()         (naval_milp_benchmark.py)  stateless, optional

Endpoints
---------
  GET    /health                      Server alive + capability check
  POST   /init_scenario               Create (or re-init) a session from Unity state
  GET    /state/{session_id}          Full snapshot for a session
  POST   /step_forward                Advance one session by N ticks
  POST   /set_weather                 Inject weather event into a session
  POST   /set_uncertainty             Update uncertainty params (applied on next init)
  POST   /run_full                    Run solver(s) to completion
  POST   /solve_milp                  Run MILP, return optimal schedule
  POST   /compare                     GA + FCFS + MILP on same scenario
  GET    /sweep                       Benchmark N seeds, download CSV
  DELETE /session/{session_id}        Remove a session from memory

Run
---
  pip install fastapi uvicorn
  python naval_api_server.py
  python naval_api_server.py --port 9000 --reload

Docs (auto-generated):
  http://localhost:8000/docs
"""

from __future__ import annotations

import argparse
import csv
import io
import random
import sys
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Import GA  (Naval_sim_core.py)
# ---------------------------------------------------------------------------
try:
    from Naval_sim_em_heuristics import NavalFinalOptimizer, VESSEL_SPECS as _VESSEL_SPECS_IMPORT
    VESSEL_SPECS = _VESSEL_SPECS_IMPORT  # use the authoritative copy from Naval_sim_em_heuristics
except ImportError:
    try:
        from Naval_sim_emissions import NavalFinalOptimizer
    except ImportError:
        print("[ERROR] Could not import NavalFinalOptimizer.")
        print("        Place Naval_sim_core.py alongside this file.")
        sys.exit(1)

# ---------------------------------------------------------------------------
# Import MILP (optional)
# ---------------------------------------------------------------------------
try:
    from MILP import build_milp, generate_small_scenario
    MILP_AVAILABLE = True
except ImportError:
    MILP_AVAILABLE = False
    print("[WARN] MILP.py not found — MILP endpoints disabled.")


# ===========================================================================
# Problem constants
# ===========================================================================

VESSEL_SPECS: Dict[str, Any] = {
    "K": {"readiness": 94, "fatigue": 8.0, "stay_range": (72,  96),  "tugs": 2,
          "cycle": 504, "count": 3,  "assigned_piers": ["P1","P2","P7","P8"]},
    "F": {"readiness": 79, "fatigue": 4.0, "stay_range": (96,  168), "tugs": 1,
          "cycle": 336, "count": 5,  "assigned_piers": ["P4","P5","P6"]},
    "L": {"readiness": 63, "fatigue": 6.0, "stay_range": (168, 168), "tugs": 2,
          "cycle": 168, "count": 4,  "assigned_piers": ["P1","P2","P7","P8"]},
    "P": {"readiness": 31, "fatigue": 1.0, "stay_range": (96,  144), "tugs": 1,
          "cycle": 240, "count": 12, "assigned_piers": ["P3","P4","P5","P6"]},
}

DEFAULT_HORIZON_H = 168
DEFAULT_SEED      = 42

# Operational uncertainty params — updated live via /set_uncertainty
_uncertainty: Dict[str, Any] = {
    "weather_prob":     0.05,   # P(weather event per tick)
    "stay_noise_frac":  0.10,   # +/- fraction noise on stay duration
    "arrival_jitter":   0,      # +/- ticks of arrival time noise
    "tug_failure_prob": 0.0,    # P(a tug unavailable per tick)
}


# ===========================================================================
# Scenario generators
# ===========================================================================

def build_ga_scenario(
    horizon_h: int = DEFAULT_HORIZON_H,
    seed: int = DEFAULT_SEED,
    vessel_counts: Dict[str, int] = None,   # override per-type counts e.g. {"K":2,"P":20}
) -> List[Dict[str, Any]]:
    """
    Procedurally generate a vessel manifest in GA format (half-hour ticks).
    Respects current _uncertainty params (stay_noise_frac, arrival_jitter).
    vessel_counts overrides the default count for each vessel type.
    """
    random.seed(seed)
    scenario: List[Dict[str, Any]] = []
    for vtype, info in VESSEL_SPECS.items():
        count = (vessel_counts or {}).get(vtype, info["count"])
        for i in range(count):
            curr_h = random.randint(0, min(info["cycle"], horizon_h))
            while curr_h < horizon_h:
                stay = random.randint(*info["stay_range"])
                noise = _uncertainty["stay_noise_frac"]
                if noise > 0:
                    stay = max(1, int(stay * (1 + random.uniform(-noise, noise))))
                arr_tick = curr_h * 2
                jitter = _uncertainty["arrival_jitter"]
                if jitter > 0:
                    arr_tick = max(0, arr_tick + random.randint(-jitter, jitter))
                scenario.append({
                    "id":       f"{vtype}{i}_{curr_h}",
                    "type":     vtype,
                    "arr":      arr_tick,
                    "arr_orig": arr_tick,
                    "stay":     stay,
                })
                curr_h += info["cycle"]
    return sorted(scenario, key=lambda v: v["arr"])


def build_milp_scenario(
    horizon_h: int = DEFAULT_HORIZON_H,
    seed: int = DEFAULT_SEED,
) -> List[Dict[str, Any]]:
    """Generate a vessel manifest in MILP format (hours)."""
    if MILP_AVAILABLE:
        return generate_small_scenario(horizon_h=horizon_h, seed=seed)
    return [{"id": v["id"], "type": v["type"],
             "arr_h": v["arr"] // 2, "stay_h": v["stay"]}
            for v in build_ga_scenario(horizon_h, seed)]


# ===========================================================================
# Canonical snapshot serialiser  (snapshot_to_dict)
# ===========================================================================

def snapshot_to_dict(sim: NavalFinalOptimizer, session_id: str = "",
                     horizon_h: int = DEFAULT_HORIZON_H) -> Dict[str, Any]:
    """
    Convert a live NavalFinalOptimizer to a fully JSON-serialisable dict.

    Attribute mapping (Naval_sim_core.py):
      sim.scenario      - vessel list (use this, not sim.vessels)
      sim.berths        - {pier: [occupant|None, ...]}
      sim.t             - current tick (half-hours)
      sim.weather_level - 0-3
      sim.weather_rem   - ticks remaining
      sim.shifting      - shift count
      sim.fatigue       - cumulative float
      sim.delay         - cumulative float in ticks (divide by 2 for hours)
      finished          - sim.t >= horizon_h * 2  (no is_finished() method)
    """
    # Berth occupancy
    berths: List[Dict] = []
    for pier, layers in sim.berths.items():
        for layer_idx, occupant in enumerate(layers):
            berths.append({
                "pier":        pier,
                "layer":       layer_idx,
                "vessel_id":   occupant["id"]   if occupant else None,
                "vessel_type": occupant["type"] if occupant else None,
                "occupied":    occupant is not None,
            })

    # Build set of currently berthed vessel ids for status tagging
    berthed_ids = {
        occ["id"]
        for layers in sim.berths.values()
        for occ in layers if occ is not None
    }

    # Vessel list lives in sim.scenario
    vessels: List[Dict] = []
    for v in sim.scenario:
        if v["id"] in berthed_ids:
            status = "berthed"
        elif v.get("arr", 0) > sim.t:
            status = "queued"
        else:
            status = "departed"
        vessels.append({
            "id":       v["id"],
            "type":     v["type"],
            "status":   status,
            "arr_tick": v["arr"],
            "arr_h":    v["arr"] // 2,
            "stay_h":   v["stay"],
        })

    finished = sim.t >= horizon_h * 2  # matches Naval_sim_core.is_finished(max_h=horizon_h)

    return {
        "session_id":    session_id,
        "tick":          sim.t,
        "time_h":        round(sim.t / 2, 2),
        "weather_level": sim.weather_level,
        "weather_rem":   sim.weather_rem,
        "finished":      finished,
        "metrics": {
            "shifting":  sim.shifting,
            "fatigue":   round(sim.fatigue, 2),
            "delay":     round(sim.delay / 2, 2),
            "emissions": round(getattr(sim, "emissions", 0.0) / 1000, 2),  # kg → tonnes
            "combined":  round(sim.shifting + sim.fatigue + sim.delay / 2, 2),
        },
        "berths":  berths,
        "vessels": vessels,
    }


# ===========================================================================
# Session store
# ===========================================================================

class Session:
    """Wraps a live simulator with its associated metadata."""

    def __init__(self, session_id: str, scenario: List[Dict], horizon_h: int,
                 seed: int, mode: str,
                 alpha: float = 0.25, beta: float = 0.25,
                 gamma: float = 0.25, delta: float = 0.25):
        self.session_id = session_id
        self.scenario   = scenario
        self.horizon_h  = horizon_h
        self.seed       = seed
        self.mode       = mode
        self.sim        = NavalFinalOptimizer(scenario, mode=mode, record_log=False)
        self.sim.alpha  = alpha
        self.sim.beta   = beta
        self.sim.gamma  = gamma
        self.sim.delta  = delta
        self.created_at = time.time()

    def set_weights(self, alpha: float, beta: float, gamma: float, delta: float):
        """Update operator weights on the running sim."""
        self.sim.alpha = alpha
        self.sim.beta  = beta
        self.sim.gamma = gamma
        self.sim.delta = delta

    def snapshot(self) -> Dict[str, Any]:
        return snapshot_to_dict(self.sim, self.session_id, self.horizon_h)


# Module-level session store
_sessions: Dict[str, Session] = {}


def _get_session(session_id: str) -> Session:
    if session_id not in _sessions:
        raise HTTPException(404, f"Session '{session_id}' not found. "
                                 "Call /init_scenario first.")
    return _sessions[session_id]


# ===========================================================================
# Pydantic models
# ===========================================================================

class UnityState(BaseModel):
    """
    Primary Unity -> server message.  Mirrors your original UnityState class
    with additions for session management and solver selection.

    Vessel tick format: {"id":"K0_0", "type":"K", "arr":0, "arr_orig":0, "stay":144}
    Leave `scenario` empty to auto-generate from seed.
    """
    scenario:         List[Dict[str, Any]] = Field(default_factory=list)
    horizon_h:        int                  = Field(DEFAULT_HORIZON_H)
    seed:             int                  = Field(DEFAULT_SEED)
    mode:             str                  = Field("GA", description="'GA' or 'FCFS'")
    vessel_counts:    Optional[Dict[str, int]] = Field(None,
                          description="Override vessel count per type e.g. {K:2, F:8, L:4, P:20}")
    current_time:     int                  = Field(0, ge=0,
                                                   description="Fast-forward to this tick")
    weather_override: Optional[int]        = Field(None, ge=0, le=3,
                                                   description="Immediately set weather level")
    force_recalc:     bool                 = Field(False,
                                                   description="Destroy and recreate session")
    session_id:       Optional[str]        = Field(None,
                                                   description="Reuse this ID (or new UUID)")


class StepRequest(BaseModel):
    session_id: str
    ticks: int = Field(1, ge=1, le=4800)


class WeatherRequest(BaseModel):
    session_id: str
    level:      int   = Field(..., ge=0, le=3)
    duration_h: float = Field(4.0, gt=0)


class WeatherEventRequest(BaseModel):
    """Operator-triggered weather change — causes GA reschedule."""
    session_id:  str
    level:       int   = Field(..., ge=0, le=3)
    duration_h:  float = Field(8.0, gt=0)


class WeightRequest(BaseModel):
    """Operator priority weights for the multi-objective GA fitness function."""
    session_id: str
    alpha: float = Field(0.25, ge=0.0, le=1.0, description="Shifting weight")
    beta:  float = Field(0.25, ge=0.0, le=1.0, description="Fatigue weight")
    gamma: float = Field(0.25, ge=0.0, le=1.0, description="Delay weight")
    delta: float = Field(0.25, ge=0.0, le=1.0, description="Emission weight")


class UncertaintyRequest(BaseModel):
    weather_prob:     Optional[float] = Field(None, ge=0.0, le=1.0)
    stay_noise_frac:  Optional[float] = Field(None, ge=0.0, le=1.0)
    arrival_jitter:   Optional[int]   = Field(None, ge=0)
    tug_failure_prob: Optional[float] = Field(None, ge=0.0, le=1.0)


class RunFullRequest(BaseModel):
    horizon_h: int                        = Field(DEFAULT_HORIZON_H)
    seed:      int                        = Field(DEFAULT_SEED)
    solver:    str                        = Field("GA",
                                                  description="'GA' | 'FCFS' | 'BOTH'")
    vessels:   Optional[List[Dict[str, Any]]] = None


class MilpRequest(BaseModel):
    horizon_h:    int                        = Field(DEFAULT_HORIZON_H)
    seed:         int                        = Field(DEFAULT_SEED)
    time_limit_s: int                        = Field(120)
    vessels:      Optional[List[Dict[str, Any]]] = None


class CompareRequest(BaseModel):
    horizon_h:    int = Field(DEFAULT_HORIZON_H)
    seed:         int = Field(DEFAULT_SEED)
    time_limit_s: int = Field(120)


# ===========================================================================
# App
# ===========================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[naval-api] Starting. MILP available: {MILP_AVAILABLE}")
    yield
    print("[naval-api] Shutdown.")


app = FastAPI(
    title="Naval Berth Digital Twin API",
    version="2.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===========================================================================
# Housekeeping
# ===========================================================================

@app.get("/health", tags=["Housekeeping"])
def health():
    """Liveness check. Unity polls this on scene start."""
    return {
        "status":      "ok",
        "version":     "2.1.0",
        "milp":        MILP_AVAILABLE,
        "sessions":    len(_sessions),
        "uncertainty": _uncertainty,
    }


@app.delete("/session/{session_id}", tags=["Housekeeping"])
def delete_session(session_id: str):
    """Remove a session (call when Unity unloads a scene)."""
    if session_id not in _sessions:
        raise HTTPException(404, f"Session '{session_id}' not found.")
    del _sessions[session_id]


@app.delete("/sessions/all", tags=["Housekeeping"])
def delete_all_sessions():
    """Clear all sessions — call on Unity scene load to avoid accumulation."""
    count = len(_sessions)
    _sessions.clear()
    return {"ok": True, "deleted": count}
    return {"ok": True, "deleted": session_id, "remaining": len(_sessions)}


# ===========================================================================
# Simulation control
# ===========================================================================

@app.post("/init_scenario", tags=["Simulation"])
def init_scenario(state: UnityState):
    """
    Create (or re-initialise) a simulation session.

    This is the primary Unity entry point — mirrors the original `init_scenario`.
    Called at scene start, on scenario changes, or on environment overrides
    (corresponds to `OnEnvironmentChange()` in the original C# client).

    Session lifecycle:
    - `session_id` omitted → fresh UUID generated and returned.
    - `session_id` exists + `force_recalc=False` → existing session returned (idempotent).
    - `force_recalc=True` → session destroyed and recreated from scratch.
    - `current_time > 0` → sim fast-forwarded to that tick before returning.
    """
    sid = state.session_id or str(uuid.uuid4())

    if sid in _sessions and not state.force_recalc:
        return {"session_id": sid, "reused": True,
                "state": _sessions[sid].snapshot()}

    scenario = state.scenario if state.scenario else build_ga_scenario(
        state.horizon_h, state.seed, state.vessel_counts)

    try:
        session = Session(
            session_id=sid,
            scenario=scenario,
            horizon_h=state.horizon_h,
            seed=state.seed,
            mode=state.mode,
        )
    except Exception as e:
        raise HTTPException(500, f"Failed to create session: {e}")

    # Fast-forward  (Unity warm-start)
    if state.current_time > 0:
        for _ in range(state.current_time):
            if session.sim.t >= session.horizon_h * 2:
                break
            session.sim.step()

    # Immediate weather override  (Unity sensor / UI input)
    if state.weather_override is not None:
        session.sim.weather_level = state.weather_override

    _sessions[sid] = session

    # Count vessels by type for debug log
    from collections import Counter
    type_counts = dict(Counter(v["type"] for v in scenario))
    counts_str = "  ".join(f"{k}:{v}" for k, v in sorted(type_counts.items()))
    print(f"[naval-api] NEW SESSION {sid[:8]}... | "
          f"{len(scenario)} vessels ({counts_str}) | "
          f"horizon={state.horizon_h}h | seed={state.seed} | mode={state.mode}")

    return {
        "session_id":   sid,
        "reused":       False,
        "vessels":      len(scenario),
        "vessel_counts": type_counts,   # e.g. {"K":3,"F":5,"L":4,"P":12}
        "horizon_h":    state.horizon_h,
        "seed":         state.seed,
        "mode":         state.mode,
        "state":        session.snapshot(),
    }


@app.get("/state/{session_id}", tags=["Simulation"])
def get_state(session_id: str):
    """Return a full snapshot (snapshot_to_dict) for the session."""
    return _get_session(session_id).snapshot()


@app.post("/step_forward", tags=["Simulation"])
def step_forward(req: StepRequest):
    """
    Advance a session by `ticks` half-hour steps.

    Maps to the original StepSimulation() coroutine in AllocatorAPIClient.
    Returns snapshot_to_dict — Unity parses this and calls UpdateVisualization().
    """
    session = _get_session(req.session_id)
    if session.sim.t >= session.horizon_h * 2:
        return {"finished": True, "state": session.snapshot()}
    try:
        for _ in range(req.ticks):
            if session.sim.t >= session.horizon_h * 2:
                break
            session.sim.step()
        return {"finished": session.sim.t >= session.horizon_h * 2, "state": session.snapshot()}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/set_weather", tags=["Simulation"])
def set_weather(req: WeatherRequest):
    """
    Inject a weather event into a running session.

    Maps to OnEnvironmentChange() when the operator changes the weather slider.
    Takes effect on the next step.
    """
    session = _get_session(req.session_id)
    try:
        session.sim.weather_level = req.level
        session.sim.weather_rem   = int(req.duration_h * 2)
        return {
            "ok":            True,
            "weather_level": session.sim.weather_level,
            "weather_rem":   session.sim.weather_rem,
            "duration_h":    req.duration_h,
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/set_weather_event", tags=["Simulation"])
def set_weather_event(req: WeatherEventRequest):
    """
    Operator-triggered weather change with GA reschedule.

    Workflow:
      1. Record metrics before change
      2. Force weather onto sim (locks out random override for duration)
      3. Re-evaluate all waiting vessels against new weather limit
         - Vessels that can no longer berth due to weather get delayed
         - Vessels that were delayed but can now berth get re-queued
      4. Return before/after metrics + affected vessel list
    """
    session = _get_session(req.session_id)
    sim     = session.sim
    t       = sim.t

    # ── Snapshot BEFORE ──────────────────────────────────────────────────────
    metrics_before = {
        "shifting": sim.shifting,
        "fatigue":  round(sim.fatigue, 2),
        "delay":    round(sim.delay / 2, 2),
        "combined": round(sim.shifting + sim.fatigue + sim.delay / 2, 2),
    }

    old_level = sim.weather_level

    # ── Force weather ─────────────────────────────────────────────────────────
    # Set level and a long rem so update_weather() won't randomise over it
    sim.weather_level  = req.level
    sim.weather_rem    = int(req.duration_h * 2) + 1   # +1 so first tick doesn't decrement to 0
    sim._forced_weather = True   # flag checked in update_weather (see Naval_sim_core patch note)

    # ── Reschedule: find affected vessels ────────────────────────────────────
    affected = []
    new_level = req.level

    for v in sim.scenario:
        spec         = VESSEL_SPECS.get(v["type"], {})
        weather_limit = spec.get("weather_limit", 0)

        # Vessel is waiting to arrive
        if v["arr"] >= t:
            if new_level > weather_limit:
                # Weather too severe — push arrival forward by duration_h * 2 ticks
                delay_ticks = int(req.duration_h * 2)
                old_arr = v["arr"]
                v["arr"] = max(v["arr"], t + delay_ticks)
                if v["arr"] != old_arr:
                    affected.append({
                        "id":     v["id"],
                        "type":   v["type"],
                        "action": "arrival_delayed",
                        "from":   old_arr // 2,
                        "to":     v["arr"] // 2,
                    })

    # Berthed vessels that need to depart but weather prevents it
    for pier, layers in sim.berths.items():
        for l_idx, v in enumerate(layers):
            if v is None:
                continue
            spec          = VESSEL_SPECS.get(v["type"], {})
            weather_limit = spec.get("weather_limit", 0)
            if new_level > weather_limit and v.get("act_dep", 9999) <= t + 4:
                old_dep = v.get("act_dep", 0)
                v["act_dep"] = t + int(req.duration_h * 2)
                affected.append({
                    "id":     v["id"],
                    "type":   v["type"],
                    "action": "departure_delayed",
                    "pier":   pier,
                    "layer":  l_idx,
                    "from":   old_dep // 2,
                    "to":     v["act_dep"] // 2,
                })

    # ── Snapshot AFTER ───────────────────────────────────────────────────────
    metrics_after = {
        "shifting": sim.shifting,
        "fatigue":  round(sim.fatigue, 2),
        "delay":    round(sim.delay / 2, 2),
        "combined": round(sim.shifting + sim.fatigue + sim.delay / 2, 2),
    }

    weather_names = {0: "Clear", 1: "Light", 2: "Moderate", 3: "Storm"}
    message = (
        f"Weather changed: {weather_names.get(old_level,'?')} → "
        f"{weather_names.get(new_level,'?')} "
        f"({len(affected)} vessels rescheduled)"
    )

    print(f"[naval-api] WEATHER EVENT | {message} | "
          f"delay {metrics_before['delay']:.1f}h → {metrics_after['delay']:.1f}h | "
          f"shifting {metrics_before['shifting']} → {metrics_after['shifting']}")
    for v in affected:
        print(f"  {v['id']} ({v['type']}): {v['action']}  "
              f"{v['from']:.0f}h → {v['to']:.0f}h")

    return {
        "ok":             True,
        "message":        message,
        "weather_level":  new_level,
        "duration_h":     req.duration_h,
        "affected":       affected,
        "metrics_before": metrics_before,
        "metrics_after":  metrics_after,
        "state":          session.snapshot(),
    }


@app.post("/set_weights", tags=["Simulation"])
def set_weights(req: WeightRequest):
    """
    Update the multi-objective GA priority weights mid-simulation.

    Weights must sum to 1.0 (Unity enforces this via slider constraint).
    Takes effect on the very next sim.step() call.

    alpha = shifting weight
    beta  = fatigue weight
    gamma = delay weight
    delta = emission weight
    """
    session = _get_session(req.session_id)
    total   = req.alpha + req.beta + req.gamma + req.delta
    if total <= 0:
        raise HTTPException(400, "Weights must sum to > 0")
    # Normalise in case of floating point drift
    alpha = req.alpha / total
    beta  = req.beta  / total
    gamma = req.gamma / total
    delta = req.delta / total
    session.set_weights(alpha, beta, gamma, delta)
    return {
        "ok":    True,
        "alpha": round(alpha, 4),
        "beta":  round(beta,  4),
        "gamma": round(gamma, 4),
        "delta": round(delta, 4),
    }


@app.post("/set_uncertainty", tags=["Simulation"])
def set_uncertainty(req: UncertaintyRequest):
    """
    Update operational uncertainty parameters (applied on next /init_scenario).

    | Param              | Effect                                          |
    |--------------------|-------------------------------------------------|
    | weather_prob       | P(spontaneous weather event per tick)           |
    | stay_noise_frac    | +/- fractional noise on each vessel stay time   |
    | arrival_jitter     | +/- ticks of noise on vessel arrival times      |
    | tug_failure_prob   | P(tug becomes unavailable per tick)             |
    """
    updates = req.model_dump(exclude_none=True)
    _uncertainty.update(updates)
    return {"ok": True, "uncertainty": _uncertainty}


# ===========================================================================
# Solvers
# ===========================================================================

@app.post("/run_full", tags=["Solvers"])
def run_full(req: RunFullRequest):
    """
    Run solver(s) to completion on a fresh scenario (blocking).

    solver: "GA" | "FCFS" | "BOTH"
    Use /init_scenario + /step_forward for frame-by-frame control.
    """
    scenario = req.vessels or build_ga_scenario(req.horizon_h, req.seed)

    def _run(mode: str) -> Dict[str, Any]:
        sim = NavalFinalOptimizer(scenario, mode=mode, record_log=False)
        t0  = time.time()
        res = sim.run(max_h=req.horizon_h)
        return {
            "mode":      mode,
            "elapsed_s": round(time.time() - t0, 3),
            "shifting":  res["shifting"],
            "fatigue":   round(res["fatigue"], 2),
            "delay":     round(res["delay"] / 2, 2),
            "combined":  round(res["shifting"] + res["fatigue"] + res["delay"] / 2, 2),
        }

    try:
        if req.solver == "BOTH":
            return {"horizon_h": req.horizon_h, "seed": req.seed,
                    "results": {"GA": _run("GA"), "FCFS": _run("FCFS")}}
        return {"horizon_h": req.horizon_h, "seed": req.seed,
                "results": _run(req.solver)}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/solve_milp", tags=["Solvers"])
def solve_milp(req: MilpRequest):
    """
    Run MILP (CBC) and return the provably optimal schedule.
    Blocking — expect 5-30 s for 168 h horizon.
    Returns full per-vessel assignments for the Unity visualiser.
    """
    if not MILP_AVAILABLE:
        raise HTTPException(501, "naval_milp_benchmark.py not found alongside server.")
    try:
        scenario = req.vessels or build_milp_scenario(req.horizon_h, req.seed)
        t0  = time.time()
        res = build_milp(scenario, horizon_h=req.horizon_h,
                         time_limit_s=req.time_limit_s)
        return {
            "status":    res["status"],
            "elapsed_s": round(time.time() - t0, 3),
            "n_vessels": res["n_vessels"],
            "results": {
                "shifting":  res["shifting"],
                "fatigue":   res["fatigue"],
                "delay":     res["delay"],
                "combined":  round(res["shifting"] + res["fatigue"] + res["delay"], 2),
                "obj_value": res["obj_value"],
            },
            "assignments": res["assignments"],
            "solve_meta": {
                "solve_time_s":  res["solve_time_s"],
                "n_vars":        res["n_vars"],
                "n_constraints": res["n_constraints"],
            },
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/compare", tags=["Solvers"])
def compare(req: CompareRequest):
    """
    Run GA, FCFS, and MILP on the SAME scenario, return gap analysis.
    Use for Unity results panels or research dashboards.
    """
    if not MILP_AVAILABLE:
        raise HTTPException(501, "naval_milp_benchmark.py not found alongside server.")
    try:
        milp_scenario = build_milp_scenario(req.horizon_h, req.seed)
        ga_scenario   = [{"id": v["id"], "type": v["type"],
                          "arr": v["arr_h"] * 2, "arr_orig": v["arr_h"] * 2,
                          "stay": v["stay_h"]} for v in milp_scenario]

        t0   = time.time()
        milp = build_milp(milp_scenario, horizon_h=req.horizon_h,
                          time_limit_s=req.time_limit_s)
        t_milp = round(time.time() - t0, 2)

        def _run(mode: str) -> Dict[str, Any]:
            sim = NavalFinalOptimizer(ga_scenario, mode=mode, record_log=False)
            res = sim.run(max_h=req.horizon_h)
            return {"shifting": res["shifting"],
                    "fatigue":  round(res["fatigue"], 2),
                    "delay":    round(res["delay"] / 2, 2)}

        ga   = _run("GA")
        fcfs = _run("FCFS")

        milp_c = round(milp["shifting"] + milp["fatigue"] + milp["delay"], 2)
        ga_c   = round(ga["shifting"]   + ga["fatigue"]   + ga["delay"],   2)
        fcfs_c = round(fcfs["shifting"] + fcfs["fatigue"] + fcfs["delay"],  2)

        def _gap(val: float, ref: float) -> Optional[float]:
            return round((val - ref) / ref * 100, 1) if ref and ref > 0 else None

        return {
            "horizon_h":    req.horizon_h,
            "seed":         req.seed,
            "n_vessels":    milp["n_vessels"],
            "milp_solve_s": t_milp,
            "results": {
                "MILP": {**{k: milp[k] for k in ("shifting","fatigue","delay")},
                         "combined": milp_c, "gap_vs_milp": 0.0,
                         "status": milp["status"]},
                "GA":   {**ga,   "combined": ga_c,
                         "gap_vs_milp": _gap(ga_c, milp_c),
                         "improvement_vs_fcfs": _gap(fcfs_c, ga_c)},
                "FCFS": {**fcfs, "combined": fcfs_c,
                         "gap_vs_milp": _gap(fcfs_c, milp_c),
                         "improvement_vs_fcfs": None},
            },
            "milp_schedule": milp["assignments"],
        }
    except Exception as e:
        raise HTTPException(500, str(e))


# ===========================================================================
# Research
# ===========================================================================

@app.get("/sweep", tags=["Research"])
def sweep(
    n_seeds:      int = Query(10, ge=1, le=200),
    horizon_h:    int = Query(DEFAULT_HORIZON_H),
    time_limit_s: int = Query(120),
    start_seed:   int = Query(0),
):
    """
    Benchmark MILP vs GA vs FCFS across N seeds. Returns CSV for download.

    curl "http://localhost:8000/sweep?n_seeds=20" -o sweep.csv
    """
    if not MILP_AVAILABLE:
        raise HTTPException(501, "naval_milp_benchmark.py not found alongside server.")

    rows: List[Dict[str, Any]] = []
    for i in range(n_seeds):
        seed = start_seed + i
        try:
            milp_scenario = build_milp_scenario(horizon_h, seed)
            ga_scenario   = [{"id": v["id"], "type": v["type"],
                               "arr": v["arr_h"] * 2, "arr_orig": v["arr_h"] * 2,
                               "stay": v["stay_h"]} for v in milp_scenario]

            t0   = time.time()
            milp = build_milp(milp_scenario, horizon_h=horizon_h,
                              time_limit_s=time_limit_s)
            t_milp = round(time.time() - t0, 2)

            def _c(mode: str) -> float:
                sim = NavalFinalOptimizer(ga_scenario, mode=mode, record_log=False)
                res = sim.run(max_h=horizon_h)
                return round(res["shifting"] + res["fatigue"] + res["delay"] / 2, 2)

            ga_c   = _c("GA")
            fcfs_c = _c("FCFS")
            milp_c = round(milp["shifting"] + milp["fatigue"] + milp["delay"], 2)

            def _gap(val: float, ref: float) -> Optional[float]:
                return round((val - ref) / ref * 100, 1) if ref and ref > 0 else None

            rows.append({
                "seed":           seed,
                "n_vessels":      milp["n_vessels"],
                "milp":           milp_c,
                "ga":             ga_c,
                "fcfs":           fcfs_c,
                "ga_gap_pct":     _gap(ga_c,   milp_c),
                "fcfs_gap_pct":   _gap(fcfs_c, milp_c),
                "ga_vs_fcfs_pct": _gap(fcfs_c, ga_c),
                "milp_status":    milp["status"],
                "milp_solve_s":   t_milp,
            })
        except Exception as e:
            rows.append({"seed": seed, "error": str(e)})

    buf = io.StringIO()
    if rows:
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=milp_ga_gap_sweep.csv"},
    )


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Naval Berth Digital Twin API")
    parser.add_argument("--host",   default="0.0.0.0")
    parser.add_argument("--port",   type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  Naval Berth Digital Twin API  v2.1.0")
    print(f"  http://localhost:{args.port}")
    print(f"  Docs:  http://localhost:{args.port}/docs")
    print(f"  MILP:  {'enabled' if MILP_AVAILABLE else 'DISABLED'}")
    print(f"{'='*60}\n")

    uvicorn.run(
        "server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )