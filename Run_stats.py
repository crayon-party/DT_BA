import sys

sys.path.insert(0, '/Users/crayonparty/Documents/SNUPEL/DT_BA')

from Naval_sim_core import NavalFinalOptimizer, generate_scenario
import statistics
import random

seeds = [0, 1, 2, 3, 42, 99, 123, 256, 512, 1000]
horizon = 168

ga_results = []
fcfs_results = []

for seed in seeds:
    random.seed(seed)
    scen = generate_scenario(max_h=horizon)

    sim_ga = NavalFinalOptimizer(scen, mode='GA', record_log=False)
    r_ga = sim_ga.run(max_h=horizon)
    ga_results.append(r_ga)

    sim_fcfs = NavalFinalOptimizer(scen, mode='FCFS', record_log=False)
    r_fcfs = sim_fcfs.run(max_h=horizon)
    fcfs_results.append(r_fcfs)

print("=" * 60)
print(f"{'Metric':<12} {'GA mean':>10} {'GA max':>10} {'FCFS mean':>10} {'FCFS max':>10}")
print("-" * 60)
for key in ['shifting', 'fatigue', 'delay']:
    ga_vals = [r[key] for r in ga_results]
    fcfs_vals = [r[key] for r in fcfs_results]
    print(f"{key:<12} {statistics.mean(ga_vals):>10.1f} {max(ga_vals):>10.1f} "
          f"{statistics.mean(fcfs_vals):>10.1f} {max(fcfs_vals):>10.1f}")

print("=" * 60)
print("\nPer-seed breakdown (GA):")
print(f"{'Seed':<8} {'Shifting':>10} {'Fatigue':>10} {'Delay':>10}")
print("-" * 40)
for seed, r in zip(seeds, ga_results):
    print(f"{seed:<8} {r['shifting']:>10} {r['fatigue']:>10.1f} {r['delay']:>10.1f}")

print("\nPer-seed breakdown (FCFS):")
print(f"{'Seed':<8} {'Shifting':>10} {'Fatigue':>10} {'Delay':>10}")
print("-" * 40)
for seed, r in zip(seeds, fcfs_results):
    print(f"{seed:<8} {r['shifting']:>10} {r['fatigue']:>10.1f} {r['delay']:>10.1f}")
