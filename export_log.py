# export_log.py
from Naval_sim_core import generate_scenario, NavalFinalOptimizer, snapshot_to_dict
import json

def export_single_run(max_h=2000):
    """Generate one scenario and export full trajectory as JSON snapshots."""
    scen = generate_scenario(max_h=max_h)
    sim = NavalFinalOptimizer(scen, mode='GA', record_log=True)
    sim.reset()
    snapshots = []

    print("Generating simulation trajectory...")
    while not sim.is_finished(max_h=max_h):
        sim.step()
        snapshots.append(snapshot_to_dict(sim))

    print(f"Exported {len(snapshots)} snapshots to naval_snapshots.json")
    with open("naval_snapshots.json", "w", encoding="utf-8") as f:
        json.dump(snapshots, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    export_single_run(2000)