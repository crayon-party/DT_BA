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
        sim  = NavalFinalOptimizer(scen, mode=mode, record_log=False)
        if mode == 'GA':
            # delay gets double weight, shifting and fatigue share the rest equally
            # alpha=shifting, beta=fatigue, gamma=delay, delta=emission
            remaining = 1.0 - delta          # weight left after emission
            sim.alpha = remaining * 0.25     # shifting: 25% of remaining
            sim.beta  = remaining * 0.25     # fatigue:  25% of remaining
            sim.gamma = remaining * 0.50     # delay:    50% of remaining
            sim.delta = delta                # emission: operator sweep
        results.append(sim.run(max_h=HORIZON))
    return (
        statistics.mean([r['shifting']  for r in results]),
        statistics.mean([r['fatigue']   for r in results]),
        statistics.mean([r['delay']     for r in results]),
        statistics.mean([r['emissions'] for r in results]),
    )


def z_score(s, f, d, e, delta=0.0):
    remaining = 1.0 - delta
    a = remaining * 0.25   # shifting weight
    b = remaining * 0.25   # fatigue weight
    g = remaining * 0.50   # delay weight
    return a*(s/S_REF) + b*(f/F_REF) + g*(d/D_REF) + delta*(e/E_REF)


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

plt.rcParams['font.family'] = 'Times New Roman'

NAVY     = '#2F4A63'
STEEL    = '#70767A'
RUST     = '#A85738'
OLIVE    = '#6E7C55'
CONCRETE = '#8A8F91'

method_labels = ['FCFS', 'EDD', 'SPT', 'URGENT', 'RT-CMOS\n(δ=0.7)']
bar_colors    = [STEEL, RUST, OLIVE, CONCRETE, NAVY]

data = {
    'Shifting':       [79.8, 79.8, 79.8, 79.8, 56.8],
    'Fatigue':        [108.7, 107.0, 107.0, 110.2, 94.8],
    'Delay (h)':      [162.3, 162.3, 162.3, 162.3, 162.0],
    'CO$_2$ (t)':     [1030.7, 1032.5, 1032.5, 1028.5, 467.8],
}

fig, axes = plt.subplots(2, 2, figsize=(26, 18))

for ax, (metric, values) in zip(axes.flatten(), data.items()):
    x    = np.arange(len(method_labels))
    bars = ax.bar(x, values, color=bar_colors, alpha=0.88,
                  edgecolor='white', linewidth=0.8, width=0.6, zorder=3)

    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + max(values) * 0.015,
                f'{val:.0f}',
                ha='center', va='bottom', fontsize=36, fontweight='bold',
                fontfamily='Times New Roman')

    ax.set_title(metric, pad=16, fontsize=40, fontweight='bold',
                 fontfamily='Times New Roman')
    ax.set_xticks(x)
    ax.set_xticklabels(method_labels, rotation=0, ha='center', fontsize=32,
                       fontfamily='Times New Roman')
    ax.tick_params(axis='y', labelsize=32)
    ax.set_ylim(0, max(values) * 1.35)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.grid(True, alpha=0.3, linestyle='--')

    bars[-1].set_edgecolor(NAVY)
    bars[-1].set_linewidth(2.5)

    ax.axvline(3.5, color='gray', linewidth=1.2, linestyle='--', alpha=0.5)

    pct_imp = (values[0] - values[-1]) / values[0] * 100
    sign    = '−' if pct_imp > 0 else '+'
    ax.text(len(method_labels) - 1, max(values) * 1.27,
            f'{sign}{abs(pct_imp):.1f}% vs FCFS',
            ha='center', va='top', fontsize=30,
            color='green' if pct_imp > 0 else 'red',
            fontweight='bold', fontfamily='Times New Roman')

plt.tight_layout()
plt.savefig('fig1_comparison_bars.png', dpi=300, bbox_inches='tight')
plt.close()
print("Saved fig1_comparison_bars.png")



# ── Figure 2: Trade-off line chart ───────────────────────────────────────────
all_deltas = [d for d, *_ in ga_rows]
impr = {
    'Shifting': [pct(fcfs_s, s) for _, s, f, d, e, z in ga_rows],
    'Fatigue':  [pct(fcfs_f, f) for _, s, f, d, e, z in ga_rows],
    'Delay':    [pct(fcfs_d, d) for _, s, f, d, e, z in ga_rows],
    'Emissions':[pct(fcfs_e, e) for _, s, f, d, e, z in ga_rows],
}
line_colors = [NAVY, OLIVE, RUST, CONCRETE]
markers     = ['o', 's', '^', 'D']

fig, ax = plt.subplots(figsize=(10, 6))

for (label, vals), color, marker in zip(impr.items(), line_colors, markers):
    ax.plot(all_deltas, vals, marker + '-', color=color, linewidth=2.5,
            markersize=8, label=label)

ax.axhline(0, color='black', linewidth=1.0, linestyle='--', alpha=0.5)
ax.axvline(0.7, color='gray', linewidth=1.5, linestyle=':', alpha=0.7)
ymin, ymax = ax.get_ylim()
ax.text(0.71, ymin + (ymax - ymin) * 0.02, 'δ=0.7\n(recommended)',
        fontsize=14, color='gray', va='bottom')
ax.set_xlabel('Emission weight δ', fontsize=16)
ax.set_ylabel('Improvement over FCFS (%)', fontsize=16)
ax.set_xticks(all_deltas)
ax.set_xticklabels([f'{d:.2f}' for d in all_deltas], fontsize=14)
ax.tick_params(axis='y', labelsize=14)
ax.legend(loc='center right', framealpha=0.9, fontsize=14)
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
ax.grid(True, alpha=0.3, linestyle='--')

plt.tight_layout()
plt.savefig('fig2_tradeoff_lines.png', dpi=300, bbox_inches='tight')
plt.close()
print("Saved fig2_tradeoff_lines.png")