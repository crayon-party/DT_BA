"""
import random
from Naval_sim_emissions import NavalFinalOptimizer, generate_scenario, VESSEL_SPECS, E_REF, F_REF

seeds = [0, 1, 42, 99, 123]
horizon = 168

for delta in [0.0, 1.0]:
    night_hits = 0
    overrides  = 0
    for seed in seeds:
        random.seed(seed)
        scen = generate_scenario(max_h=horizon)
        sim  = NavalFinalOptimizer(scen, mode='GA', record_log=True)
        sim.delta = delta
        sim.alpha = sim.beta = sim.gamma = (1 - delta) / 3
        r = sim.run(max_h=horizon)
        for e in r['history']:
            if e['Event'] == 'Arrival':
                tick = int(e['Time'] * 2)
                if (tick % 48) >= 44 or (tick % 48) <= 14:
                    night_hits += 1
        print(f"  seed={seed} emissions={r['emissions']/1000:.1f}t delay={r['delay']:.1f}h")
    print(f"delta={delta:.1f}: total night arrivals={night_hits}")
    print()
----------------------------
import random, statistics
from Naval_sim_emissions import NavalFinalOptimizer, generate_scenario

seeds = [0, 1, 2, 3, 42, 99, 123, 256, 512, 1000]
horizon = 168
S_REF, F_REF, D_REF, E_REF = 300, 400, 600, 250000

print(f"{'delta':<8} {'Shifting':>9} {'Fatigue':>9} {'Delay':>9} {'CO2 (t)':>9} {'Z':>7}")
print("-" * 58)

for delta in [0.0, 0.25, 0.50, 0.75, 1.0]:
    w = (1 - delta) / 3
    results = []
    for seed in seeds:
        random.seed(seed)
        scen = generate_scenario(max_h=horizon)
        sim  = NavalFinalOptimizer(scen, mode='GA', record_log=False)
        sim.alpha = w
        sim.beta  = w
        sim.gamma = w
        sim.delta = delta
        results.append(sim.run(max_h=horizon))

    s = statistics.mean([r['shifting']  for r in results])
    f = statistics.mean([r['fatigue']   for r in results])
    d = statistics.mean([r['delay']     for r in results])
    e = statistics.mean([r['emissions'] for r in results])
    z = w*(s/S_REF) + w*(f/F_REF) + w*(d/D_REF) + delta*(e/E_REF)
    print(f"{delta:<8.2f} {s:>9.1f} {f:>9.1f} {d:>9.1f} {e/1000:>9.1f} {z:>7.3f}")
"""
"""
comparison.py
=============
Compares GA (at each delta weight) against FCFS baseline.
Run from the DT_BA directory:
    python3 comparison.py
"""
"""
import random
import statistics
from Naval_sim_em_heuristics import NavalFinalOptimizer, generate_scenario

SEEDS = [0, 1, 2, 3, 42, 99, 123, 256, 512, 1000]
HORIZON = 168
S_REF, F_REF, D_REF, E_REF = 300, 400, 600, 1000000

# ── FCFS baseline (no weights, fixed behaviour) ───────────────────────────────
fcfs_results = []
for seed in SEEDS:
    random.seed(seed)
    scen = generate_scenario(max_h=HORIZON)
    sim = NavalFinalOptimizer(scen, mode='FCFS', record_log=False)
    fcfs_results.append(sim.run(max_h=HORIZON))

fcfs_s = statistics.mean([r['shifting'] for r in fcfs_results])
fcfs_f = statistics.mean([r['fatigue'] for r in fcfs_results])
fcfs_d = statistics.mean([r['delay'] for r in fcfs_results])
fcfs_e = statistics.mean([r['emissions'] for r in fcfs_results])

# ── GA at each delta ──────────────────────────────────────────────────────────
ga_rows = []
for delta in [0.00, 0.25, 0.4,  0.50, 0.6, 0.7, 0.75, 0.8, 0.9, 1.00]:
    w = (1 - delta) / 3
    results = []
    for seed in SEEDS:
        random.seed(seed)
        scen = generate_scenario(max_h=HORIZON)
        sim = NavalFinalOptimizer(scen, mode='GA', record_log=False)
        sim.alpha = w
        sim.beta = w
        sim.gamma = w
        sim.delta = delta
        results.append(sim.run(max_h=HORIZON))

    s = statistics.mean([r['shifting'] for r in results])
    f = statistics.mean([r['fatigue'] for r in results])
    d = statistics.mean([r['delay'] for r in results])
    e = statistics.mean([r['emissions'] for r in results])
    z = w * (s / S_REF) + w * (f / F_REF) + w * (d / D_REF) + delta * (e / E_REF)
    ga_rows.append((delta, s, f, d, e, z))

# ── Print results ─────────────────────────────────────────────────────────────
print("=" * 78)
print("RESULTS TABLE — GA (multi-objective) vs FCFS baseline")
print(f"Horizon: {HORIZON}h  |  Seeds: {len(SEEDS)}  |  Ref: S={S_REF} F={F_REF} D={D_REF} E={E_REF:,}")
print("=" * 78)
print(f"{'Method':<16} {'Shift':>7} {'Fatigue':>9} {'Delay':>8} {'CO2(t)':>8} {'Z':>7}")
print("-" * 78)

# FCFS row (Z computed at equal weights 0.25 each for comparison)
fcfs_z = 0.25 * (fcfs_s / S_REF) + 0.25 * (fcfs_f / F_REF) + 0.25 * (fcfs_d / D_REF) + 0.25 * (fcfs_e / E_REF)
print(f"{'FCFS (baseline)':<16} {fcfs_s:>7.1f} {fcfs_f:>9.1f} {fcfs_d:>8.1f} {fcfs_e / 1000:>8.1f} {fcfs_z:>7.3f}")
print("-" * 78)

for delta, s, f, d, e, z in ga_rows:
    label = f"GA  δ={delta:.2f}"
    print(f"{label:<16} {s:>7.1f} {f:>9.1f} {d:>8.1f} {e / 1000:>8.1f} {z:>7.3f}")

print("=" * 78)

# ── Improvement vs FCFS ───────────────────────────────────────────────────────
print("\nGA improvement over FCFS (%) — at each delta:")
print(f"{'Method':<16} {'Shift%':>8} {'Fatigue%':>10} {'Delay%':>8} {'CO2%':>8}")
print("-" * 50)
for delta, s, f, d, e, z in ga_rows:
    ds = (fcfs_s - s) / fcfs_s * 100 if fcfs_s > 0 else 0
    df = (fcfs_f - f) / fcfs_f * 100 if fcfs_f > 0 else 0
    dd = (fcfs_d - d) / fcfs_d * 100 if fcfs_d > 0 else 0
    de = (fcfs_e - e) / fcfs_e * 100 if fcfs_e > 0 else 0
    label = f"GA  δ={delta:.2f}"
    print(f"{label:<16} {ds:>+7.1f}% {df:>+9.1f}% {dd:>+7.1f}% {de:>+7.1f}%")

print()
print("Note: positive % = GA better than FCFS")
print("      negative % = GA worse than FCFS")
"""
import random
import statistics
from Naval_sim_em_heuristics import NavalFinalOptimizer, generate_scenario

SEEDS = [0, 1, 2, 3, 42, 99, 123, 256, 512, 1000]
HORIZON = 168
S_REF, F_REF, D_REF, E_REF = 300, 400, 600, 1000000


def run_mode(mode, delta=0.0):
    results = []
    for seed in SEEDS:
        random.seed(seed)
        scen = generate_scenario(max_h=HORIZON)
        sim = NavalFinalOptimizer(scen, mode=mode, record_log=False)
        if mode == 'GA':
            w = (1 - delta) / 3
            sim.alpha = w;
            sim.beta = w;
            sim.gamma = w;
            sim.delta = delta
        results.append(sim.run(max_h=HORIZON))
    return (
        statistics.mean([r['shifting'] for r in results]),
        statistics.mean([r['fatigue'] for r in results]),
        statistics.mean([r['delay'] for r in results]),
        statistics.mean([r['emissions'] for r in results]),
    )


def z_score(s, f, d, e, delta=0.0):
    if delta == 0.0:
        return 0.25 * (s / S_REF) + 0.25 * (f / F_REF) + 0.25 * (d / D_REF) + 0.25 * (e / E_REF)
    w = (1 - delta) / 3
    return w * (s / S_REF) + w * (f / F_REF) + w * (d / D_REF) + delta * (e / E_REF)


# ── Run all methods ───────────────────────────────────────────────────────────
baselines = {
    'FCFS': run_mode('FCFS'),
    'EDD': run_mode('EDD'),
    'SPT': run_mode('SPT'),
    'URGENT': run_mode('URGENT'),
}

ga_deltas = [0.00, 0.25, 0.40, 0.50, 0.60, 0.70, 0.75, 0.80, 0.90, 1.00]
ga_rows = []
for delta in ga_deltas:
    s, f, d, e = run_mode('GA', delta)
    ga_rows.append((delta, s, f, d, e, z_score(s, f, d, e, delta)))

fcfs_s, fcfs_f, fcfs_d, fcfs_e = baselines['FCFS']

# ── Results table ─────────────────────────────────────────────────────────────
print("=" * 78)
print("RESULTS TABLE — GA vs Baselines (FCFS, EDD, SPT, URGENT)")
print(f"Horizon: {HORIZON}h  |  Seeds: {len(SEEDS)}  |  "
      f"Ref: S={S_REF} F={F_REF} D={D_REF} E={E_REF:,}")
print("=" * 78)
print(f"{'Method':<16} {'Shift':>7} {'Fatigue':>9} {'Delay':>8} {'CO2(t)':>8} {'Z':>7}")
print("-" * 78)

for name, (s, f, d, e) in baselines.items():
    print(f"{name:<16} {s:>7.1f} {f:>9.1f} {d:>8.1f} {e / 1000:>8.1f} {z_score(s, f, d, e):>7.3f}")
print("-" * 78)

for delta, s, f, d, e, z in ga_rows:
    print(f"{'GA  d=' + str(delta):<16} {s:>7.1f} {f:>9.1f} {d:>8.1f} {e / 1000:>8.1f} {z:>7.3f}")
print("=" * 78)


# ── Improvement vs FCFS ───────────────────────────────────────────────────────
def pct(base, val):
    return (base - val) / base * 100 if base > 0 else 0


print("\nImprovement vs FCFS (positive = better than FCFS):")
print(f"{'Method':<16} {'Shift%':>8} {'Fatigue%':>10} {'Delay%':>8} {'CO2%':>8}")
print("-" * 54)

for name, (s, f, d, e) in baselines.items():
    if name == 'FCFS': continue
    print(f"{name:<16} {pct(fcfs_s, s):>+7.1f}% {pct(fcfs_f, f):>+9.1f}% "
          f"{pct(fcfs_d, d):>+7.1f}% {pct(fcfs_e, e):>+7.1f}%")
print("-" * 54)

for delta, s, f, d, e, z in ga_rows:
    label = "GA  d=" + str(delta)
    print(f"{label:<16} {pct(fcfs_s, s):>+7.1f}% {pct(fcfs_f, f):>+9.1f}% "
          f"{pct(fcfs_d, d):>+7.1f}% {pct(fcfs_e, e):>+7.1f}%")

print("\nNote: positive = better than FCFS, negative = worse than FCFS")

# ── Plots ─────────────────────────────────────────────────────────────────────
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams.update({
    'font.family': 'DejaVu Sans', 'font.size': 11,
    'axes.titlesize': 12, 'axes.titleweight': 'bold',
    'axes.spines.top': False, 'axes.spines.right': False,
    'axes.grid': True, 'grid.alpha': 0.3, 'grid.linestyle': '--',
    'figure.dpi': 150, 'savefig.dpi': 300, 'savefig.bbox': 'tight',
})

NAVY, STEEL, RUST, OLIVE, CONCRETE = '#2F4A63', '#70767A', '#A85738', '#6E7C55', '#8A8F91'
# ── Figure 1: Bar chart — all methods, 4 metrics ─────────────────────────────
fig, axes = plt.subplots(2, 2, figsize=(12, 8))
fig.suptitle('Performance Comparison: GA vs Baseline Methods\n(10-seed average, 168h horizon)',
             fontsize=13, fontweight='bold', y=1.01)

selected_deltas = [0.00, 0.25, 0.50, 0.75, 1.00]
method_labels = ['FCFS', 'EDD', 'SPT', 'URGENT'] + [f'GA δ={d:.2f}' for d in selected_deltas]
bar_colors = [STEEL, RUST, OLIVE, CONCRETE] + [NAVY] * len(selected_deltas)

metric_titles = ['Shifting events', 'Fatigue score', 'Delay (hours)', 'CO₂ emissions (t)']

for ax, (title, idx) in zip(axes.flatten(), zip(metric_titles, range(4))):
    values = (
            [baselines['FCFS'][idx], baselines['EDD'][idx],
             baselines['SPT'][idx], baselines['URGENT'][idx]] +
            [d[idx] if idx < 3 else d[idx] / 1000
             for delta, *d, z in ga_rows if delta in selected_deltas]
    )
    x = np.arange(len(method_labels))
    bars = ax.bar(x, values, color=bar_colors, alpha=0.85,
                  edgecolor='white', linewidth=0.5, zorder=3)
    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max(values) * 0.01,
                f'{val:.0f}', ha='center', va='bottom', fontsize=8.5)
    ax.set_title(title)
    ax.set_xticks(x)
    ax.set_xticklabels(method_labels, rotation=40, ha='right', fontsize=9)
    ax.set_ylim(0, max(values) * 1.2)
    ax.axvline(3.5, color=NAVY, linewidth=0.8, linestyle=':', alpha=0.5)

plt.tight_layout()
plt.savefig('fig1_comparison_bars.png')
plt.close()
print("\nSaved fig1_comparison_bars.png")

# ── Figure 2: Trade-off line chart ───────────────────────────────────────────
all_deltas = [d for d, *_ in ga_rows]
impr = {
    'Shifting': [pct(fcfs_s, s) for _, s, f, d, e, z in ga_rows],
    'Fatigue': [pct(fcfs_f, f) for _, s, f, d, e, z in ga_rows],
    'Delay': [pct(fcfs_d, d) for _, s, f, d, e, z in ga_rows],
    'Emissions': [pct(fcfs_e, e) for _, s, f, d, e, z in ga_rows],
}
line_colors = [NAVY, OLIVE, RUST, CONCRETE]
markers = ['o', 's', '^', 'D']

fig, ax = plt.subplots(figsize=(10, 5.5))
for (label, vals), color, marker in zip(impr.items(), line_colors, markers):
    ax.plot(all_deltas, vals, marker + '-', color=color, linewidth=2,
            markersize=5, label=label)

ax.axhline(0, color='black', linewidth=0.8, linestyle='--', alpha=0.5)
ax.axvline(0.75, color='gray', linewidth=1.0, linestyle=':', alpha=0.7)
ymin, ymax = ax.get_ylim()
ax.text(0.76, ymin + (ymax - ymin) * 0.02, 'δ=0.75\n(recommended)',
        fontsize=9, color='gray', va='bottom')
ax.set_xlabel('Emission weight δ')
ax.set_ylabel('Improvement over FCFS (%)')
ax.set_title('GA Trade-off Across Emission Weight δ\n(positive = GA better than FCFS)',
             fontweight='bold')
ax.set_xticks(all_deltas)
ax.set_xticklabels([f'{d:.2f}' for d in all_deltas])
ax.legend(loc='center right', framealpha=0.9, fontsize=10)
plt.tight_layout()
plt.savefig('fig2_tradeoff_lines.png')
plt.close()
print("Saved fig2_tradeoff_lines.png")