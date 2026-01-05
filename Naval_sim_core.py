import random
import numpy as np
import pandas as pd
from collections import Counter

# 1. 함종 및 부두 설정
VESSEL_SPECS = {
    'K': {'readiness': 94, 'fatigue': 8.0, 'stay_range': (72, 96), 'tugs': 2, 'duration': 2, 'cycle': 504, 'count': 3,
          'assigned_piers': ['P1', 'P2', 'P7', 'P8'], 'weather_limit': 2},
    'F': {'readiness': 79, 'fatigue': 4.0, 'stay_range': (96, 168), 'tugs': 1, 'duration': 1, 'cycle': 336, 'count': 5,
          'assigned_piers': ['P4', 'P5', 'P6'], 'weather_limit': 1},
    'L': {'readiness': 63, 'fatigue': 6.0, 'stay_range': (168, 168), 'tugs': 2, 'duration': 2, 'cycle': 168, 'count': 4,
          'assigned_piers': ['P1', 'P2', 'P7', 'P8'], 'weather_limit': 1},
    'P': {'readiness': 31, 'fatigue': 1.0, 'stay_range': (96, 144), 'tugs': 1, 'duration': 1, 'cycle': 240, 'count': 12,
          'assigned_piers': ['P3', 'P4', 'P5', 'P6'], 'weather_limit': 0}
}

PIER_CONFIG = {
    'P1': {'layers': 3}, 'P2': {'layers': 3}, 'P3': {'layers': 1},
    'P4': {'layers': 2}, 'P5': {'layers': 2}, 'P6': {'layers': 2},
    'P7': {'layers': 3}, 'P8': {'layers': 3}
}


class NavalFinalOptimizer:
    def __init__(self, scenario, mode='GA', record_log=True):
        # store original for reset capability
        self.initial_scenario = [v.copy() for v in scenario]
        self.mode = mode
        self.record_log = record_log
        self.reset()

    def reset(self):
        # NEW: time index
        self.t = 0

        # original state
        self.berths = {p: [None] * PIER_CONFIG[p]['layers'] for p in PIER_CONFIG}
        self.scenario = [v.copy() for v in self.initial_scenario]
        self.tug_free_time = [0] * 6
        self.shifting, self.fatigue, self.delay = 0, 0, 0
        self.vessel_history = []
        self.weather_level = 0
        self.weather_rem = 0
        self.counts = Counter()
        self.last_move_dict = {}

    # ---- ALL ORIGINAL HELPER METHODS UNCHANGED ----
    def update_weather(self, t):
        if self.weather_rem <= 0:
            if random.random() < 0.05:
                self.weather_level = random.choice([1, 2, 3])
                self.weather_rem = random.randint(2, 8)
            else:
                self.weather_level = 0
        else:
            self.weather_rem -= 1
        return self.weather_level

    def is_night(self, t):
        return (t % 48) >= 44 or (t % 48) <= 14

    def check_compatibility(self, type1, type2):
        if type1 == type2: return True
        pair = {type1, type2}
        if pair == {'K', 'P'} or pair == {'P', 'L'}: return False
        return True

    def calculate_vessel_fatigue(self, vessel_id, v_type, t, is_shifting=False):
        spec_f = VESSEL_SPECS[v_type]['fatigue']
        multiplier = 10 if self.is_night(t) else 1
        total_f = spec_f * multiplier
        if is_shifting: total_f *= 1.5
        return total_f

    def evaluate_fitness(self, v, p_id, l_idx, t, wait_time):
        if self.berths[p_id][l_idx] is not None: return 1e15
        if p_id not in VESSEL_SPECS[v['type']]['assigned_piers']: return 1e15
        for i, other in enumerate(self.berths[p_id]):
            if other and abs(i - l_idx) == 1:
                if not self.check_compatibility(v['type'], other['type']): return 2e15
        if self.mode == 'FCFS': return int(p_id[1:]) * 10 + l_idx

        penalty = 0
        curr_f = self.calculate_vessel_fatigue(v['id'], v['type'], t)
        penalty += curr_f * 200
        penalty -= (wait_time * 300)
        my_dep = t + (v['stay'] * 2)
        for i, other in enumerate(self.berths[p_id]):
            if other:
                if (l_idx < i and my_dep < other['dep_t']) or (l_idx > i and my_dep > other['dep_t']):
                    penalty += 50000
        return penalty

    # ---- NEW: single step ----
    def step(self, max_h=2000):
        """Advance by one time step."""
        t = self.t
        if t >= max_h * 2:
            return

        w_lvl = self.update_weather(t)
        is_lunch = (t % 48) in [24, 25]
        avail_tugs = 0 if (is_lunch or w_lvl == 3) else sum(1 for f in self.tug_free_time if f <= t)

        # 1. 출항 처리 (identical to your run(), using self.t)
        out_list = []
        for p, layers in self.berths.items():
            for i, v in enumerate(layers):
                if v and v['act_dep'] <= t: out_list.append((p, i, v))
        for p, i, v in sorted(out_list, key=lambda x: VESSEL_SPECS[x[2]['type']]['readiness'], reverse=True):
            spec = VESSEL_SPECS[v['type']]
            if w_lvl <= spec['weather_limit'] and avail_tugs >= spec['tugs']:
                # [v11.1] 피로도 안전장치: 야간 출항 시 일정 피로도 이상이면 억제
                if self.mode == 'GA' and self.is_night(t):
                    if self.calculate_vessel_fatigue(v['id'], v['type'], t) > 50:
                        v['act_dep'] += 1
                        self.delay += 0.5
                        continue

                blockers = [self.berths[p][j] for j in range(i + 1, len(self.berths[p])) if self.berths[p][j]]
                if not blockers:
                    assigned = 0
                    for tid in range(6):
                        if self.tug_free_time[tid] <= t and assigned < spec['tugs']:
                            self.tug_free_time[tid] = t + spec['duration']
                            assigned += 1
                    self.fatigue += self.calculate_vessel_fatigue(v['id'], v['type'], t)
                    self.counts["Total_Departure"] += 1
                    if self.record_log:
                        self.vessel_history.append(
                            {'Time': t / 2, 'VesselID': v['id'], 'Event': 'Departure', 'Loc': f"{p}-{i}",
                             'Weather': w_lvl, 'Tugs': avail_tugs})
                    self.berths[p][i] = None
                    avail_tugs -= spec['tugs']
                else:
                    self.shifting += 1
                    v['act_dep'] += 1
                    self.delay += 0.5
            else:
                v['act_dep'] += 1
                self.delay += 0.5

        # 2. 입항 처리 (identical logic)
        for v in self.scenario:
            wait_time = max(0, t - v['arr_orig'])
            if v['arr'] == t:
                spec = VESSEL_SPECS[v['type']]
                if avail_tugs >= spec['tugs'] and w_lvl <= spec['weather_limit']:
                    # [v11.1] 야간 입항 억제
                    if self.mode == 'GA' and self.is_night(t) and wait_time < 12:
                        v['arr'] += 1
                        self.delay += 0.5
                        continue

                    best_s, best_p, best_l = 1e15, None, None
                    for p_id in PIER_CONFIG:
                        for l_idx in range(PIER_CONFIG[p_id]['layers']):
                            s = self.evaluate_fitness(v, p_id, l_idx, t, wait_time)
                            if s < best_s: best_s, best_p, best_l = s, p_id, l_idx

                    if best_p and best_s < 1e15:
                        assigned = 0
                        for tid in range(6):
                            if self.tug_free_time[tid] <= t and assigned < spec['tugs']:
                                self.tug_free_time[tid] = t + spec['duration']
                                assigned += 1
                        v['act_dep'] = t + (v['stay'] * 2)
                        v['dep_t'] = v['act_dep']
                        self.berths[best_p][best_l] = v
                        self.fatigue += self.calculate_vessel_fatigue(v['id'], v['type'], t)
                        self.counts["Total_Arrival"] += 1
                        if self.record_log:
                            self.vessel_history.append({
                                'Time': t / 2, 'VesselID': v['id'], 'Event': 'Arrival',
                                'Loc': f"{best_p}-{best_l}", 'Weather': w_lvl, 'Tugs': avail_tugs
                            })
                    else:
                        v['arr'] += 1
                        self.delay += 0.5
                else:
                    v['arr'] += 1
                    self.delay += 0.5

        # advance time
        self.t += 1

    # ---- NEW: finished check ----
    def is_finished(self, max_h=2000):
        return self.t >= max_h * 2

    # ---- ORIGINAL run() PRESERVED ----
    def run(self, max_h=2000):
        self.reset()
        for _ in range(max_h * 2):
            self.step(max_h=max_h)
        return {
            'shifting': self.shifting,
            'fatigue': self.fatigue,
            'delay': self.delay,
            'counts': dict(self.counts),
            'history': self.vessel_history
        }
def snapshot_to_dict(sim: NavalFinalOptimizer):
    """JSON snapshot for Unity."""
    t = sim.t
    w_lvl = sim.weather_level
    is_night = sim.is_night(t)
    is_lunch = (t % 48) in [24, 25]

    # ships at berths
    ships_state = []
    for p_id, layers in sim.berths.items():
        for l_idx, v in enumerate(layers):
            if v is not None:
                status = "AT_BERTH"
                if hasattr(v, 'act_dep') and v['act_dep'] <= t:
                    status = "READY_DEPART"
                ships_state.append({
                    "id": v["id"],
                    "type": v["type"],
                    "status": status,
                    "pier": p_id,
                    "layer": l_idx,
                    "arr_time": v.get("arr", None),
                    "dep_planned": v.get("dep_t", None),
                    "dep_actual": v.get("act_dep", None)
                })

    # waiting/departed ships (coarse)
    berthed_ids = {s["id"] for s in ships_state}
    for v in sim.scenario:
        if v["id"] not in berthed_ids:
            if v["arr"] > t:
                status = "FUTURE"
            elif "act_dep" in v and v["act_dep"] <= t:
                status = "DEPARTED"
            else:
                status = "WAITING"
            ships_state.append({
                "id": v["id"],
                "type": v["type"],
                "status": status,
                "pier": None,
                "layer": None,
                "arr_time": v.get("arr", None),
                "dep_planned": v.get("dep_t", None),
                "dep_actual": v.get("act_dep", None)
            })

    # tugs
    tugs_state = []
    for tid, free_t in enumerate(sim.tug_free_time):
        tugs_state.append({
            "id": f"T{tid+1}",
            "status": "IDLE" if free_t <= t else "BUSY",
            "free_time": free_t
        })

    return {
        "type": "STATE",
        "time": t,
        "weather": w_lvl,
        "is_night": is_night,
        "is_lunch": is_lunch,
        "ships": ships_state,
        "tugs": tugs_state,
        "metrics": {
            "shifting": sim.shifting,
            "fatigue": sim.fatigue,
            "delay": sim.delay
        }
    }


def generate_scenario(max_h=2000):
    scen = []
    for tc, info in VESSEL_SPECS.items():
        for i in range(info['count']):
            curr_h = random.randint(0, info['cycle'])
            while curr_h < max_h:
                scen.append({'id': f'{tc}{i}_{curr_h}', 'type': tc, 'arr': curr_h * 2, 'arr_orig': curr_h * 2,
                             'stay': random.randint(*info['stay_range'])})
                curr_h += info['cycle']
    return sorted(scen, key=lambda x: x['arr'])


def run_experiment(iterations=1000):
    ga_results, fcfs_results = [], []
    best_log, best_delay, best_counts = [], float('inf'), {}

    print(f"[{iterations}회 실험] v11.1 피로도 양수 전환 및 지연 최적화 실행 중...")
    for i in range(iterations):
        scen = generate_scenario()
        sim_ga = NavalFinalOptimizer(scen, mode='GA', record_log=True)
        res_ga = sim_ga.run()
        ga_results.append({'shifting': res_ga['shifting'], 'fatigue': res_ga['fatigue'], 'delay': res_ga['delay']})
        if res_ga['delay'] < best_delay:
            best_delay, best_log, best_counts = res_ga['delay'], res_ga['history'], res_ga['counts']

        sim_fcfs = NavalFinalOptimizer(scen, mode='FCFS', record_log=False)
        res_fcfs = sim_fcfs.run()
        fcfs_results.append(
            {'shifting': res_fcfs['shifting'], 'fatigue': res_fcfs['fatigue'], 'delay': res_fcfs['delay']})
        if (i + 1) % 100 == 0: print(f"> 진행: {i + 1:4d}/{iterations}")

    df_ga, df_fc = pd.DataFrame(ga_results), pd.DataFrame(fcfs_results)
    print("\n" + "=" * 85 + "\n[v11.1 최종 실험 결과 - 피로도 방어 성공]\n" + "-" * 85)
    for key in ['shifting', 'fatigue', 'delay']:
        avg_ga, avg_fc = df_ga[key].mean(), df_fc[key].mean()
        impr = ((avg_fc - avg_ga) / avg_fc * 100) if avg_fc > 0 else 0
        print(f"{key:<12} | GA: {avg_ga:<13.2f} | FCFS: {avg_fc:<14.2f} | 개선율: {impr:>6.1f}%")
    print("=" * 85)

    pd.DataFrame(best_log).to_csv("naval_operation_log.csv", index=False, encoding='utf-8-sig')
    summary_df = pd.concat([df_ga.add_prefix('GA_'), df_fc.add_prefix('FCFS_')], axis=1)
    summary_df.to_csv("naval_results_v11_1.csv", index=False, encoding='utf-8-sig')


if __name__ == "__main__":
    run_experiment(1000)
