import random
import statistics
from Naval_sim_em_heuristics import NavalFinalOptimizer, generate_scenario

SEEDS = [0, 1, 2, 3, 42, 99, 123, 256, 512, 1000]
HORIZON = 168
F_REF, D_REF, E_REF = 400, 600, 1000000  # shifting removed from Z


# gamma = emission weight
# alpha = fatigue weight, beta = delay weight
# alpha + beta + gamma = 1, equal split when gamma=1/3

def run_mode(mode, gamma=1 / 3):
    results = []
    for seed in SEEDS:
        random.seed(seed)
        scen = generate_scenario(max_h=HORIZON)
        sim = NavalFinalOptimizer(scen, mode=mode, record_log=False)
        if mode == 'GA':
            rem = (1 - gamma) / 2  # equal split of remaining weight between alpha and beta
            sim.alpha = rem  # fatigue
            sim.beta = rem  # delay
            sim.gamma = 0.0  # shifting weight — kept at 0, shifting not in Z
            sim.delta = gamma  # emission weight (delta in code = gamma in paper)
        results.append(sim.run(max_h=HORIZON))
    return (
        statistics.mean([r['shifting'] for r in results]),
        statistics.mean([r['fatigue'] for r in results]),
        statistics.mean([r['delay'] for r in results]),
        statistics.mean([r['emissions'] for r in results]),
    )


def z_score(f, d, e, gamma=1 / 3):
    """3-criterion Z: alpha=fatigue, beta=delay, gamma=emissions"""
    rem = (1 - gamma) / 2
    return rem * (f / F_REF) + rem * (d / D_REF) + gamma * (e / E_REF)


# ── Run all methods ───────────────────────────────────────────────────────────
baselines = {
    'FCFS': run_mode('FCFS'),
    'EDD': run_mode('EDD'),
    'SPT': run_mode('SPT'),
    'URGENT': run_mode('URGENT'),
}

# gamma sweep: emission weight from 0 to 1
ga_gammas = [0.00, 0.25, 0.40, 0.50, 0.60, 0.70, 0.75, 0.80, 0.90, 1.00]
ga_rows = []
for gamma in ga_gammas:
    s, f, d, e = run_mode('GA', gamma)
    ga_rows.append((gamma, s, f, d, e, z_score(f, d, e, gamma)))

fcfs_s, fcfs_f, fcfs_d, fcfs_e = baselines['FCFS']

# ── Results table ─────────────────────────────────────────────────────────────
print("=" * 78)
print("RESULTS TABLE — GA (3-criterion) vs Baselines (FCFS, EDD, SPT, URGENT)")
print(f"Horizon: {HORIZON}h  |  Seeds: {len(SEEDS)}  |  "
      f"Ref: F={F_REF} D={D_REF} E={E_REF:,}")
print("Z = α·(F/F_ref) + β·(D/D_ref) + γ·(E/E_ref),  α+β+γ=1,  α=β=(1-γ)/2")
print("=" * 78)
print(f"{'Method':<16} {'Shift':>7} {'Fatigue':>9} {'Delay':>8} {'CO2(t)':>8} {'Z':>7}")
print("-" * 78)

for name, (s, f, d, e) in baselines.items():
    z = z_score(f, d, e)
    print(f"{name:<16} {s:>7.1f} {f:>9.1f} {d:>8.1f} {e / 1000:>8.1f} {z:>7.3f}")
print("-" * 78)

for gamma, s, f, d, e, z in ga_rows:
    label = f"GA  γ={gamma:.2f}"
    print(f"{label:<16} {s:>7.1f} {f:>9.1f} {d:>8.1f} {e / 1000:>8.1f} {z:>7.3f}")
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

for gamma, s, f, d, e, z in ga_rows:
    label = f"GA  γ={gamma:.2f}"
    print(f"{label:<16} {pct(fcfs_s, s):>+7.1f}% {pct(fcfs_f, f):>+9.1f}% "
          f"{pct(fcfs_d, d):>+7.1f}% {pct(fcfs_e, e):>+7.1f}%")

print("\nNote: positive = better than FCFS, negative = worse than FCFS")
print("Shifting reported as secondary metric only — not in Z")

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

BLUE, GRAY, CORAL, GREEN, PURPLE = '#2E5FA3', '#888780', '#D85A30', '#1D9E75', '#7F77DD'

# ── Figure 1: Bar chart — all methods, 4 reported metrics ────────────────────
fig, axes = plt.subplots(2, 2, figsize=(12, 8))
fig.suptitle('Performance Comparison: GA vs Baseline Methods\n(10-seed average, 168h horizon)',
             fontsize=13, fontweight='bold', y=1.01)

selected_gammas = [0.00, 0.25, 0.50, 0.75, 1.00]
method_labels = ['FCFS', 'EDD', 'SPT', 'URGENT'] + [f'GA γ={g:.2f}' for g in selected_gammas]
bar_colors = [GRAY, CORAL, GREEN, PURPLE] + [BLUE] * len(selected_gammas)

metric_titles = ['Shifting events (secondary)', 'Fatigue score', 'Delay (hours)', 'CO₂ emissions (t)']

for ax, (title, idx) in zip(axes.flatten(), zip(metric_titles, range(4))):
    values = (
            [baselines['FCFS'][idx], baselines['EDD'][idx],
             baselines['SPT'][idx], baselines['URGENT'][idx]] +
            [row[idx + 1] if idx < 3 else row[idx + 1] / 1000
             for row in ga_rows if row[0] in selected_gammas]
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
    ax.axvline(3.5, color=BLUE, linewidth=0.8, linestyle=':', alpha=0.5)

plt.tight_layout()
plt.savefig('fig1_comparison_bars.png')
plt.close()
print("\nSaved fig1_comparison_bars.png")

# ── Figure 2: Trade-off line chart across gamma ───────────────────────────────
all_gammas = [row[0] for row in ga_rows]
impr = {
    'Shifting (secondary)': [pct(fcfs_s, row[1]) for row in ga_rows],
    'Fatigue': [pct(fcfs_f, row[2]) for row in ga_rows],
    'Delay': [pct(fcfs_d, row[3]) for row in ga_rows],
    'Emissions': [pct(fcfs_e, row[4]) for row in ga_rows],
}
line_colors = [GRAY, BLUE, CORAL, GREEN]
markers = ['x', 's', '^', 'D']

fig, ax = plt.subplots(figsize=(10, 5.5))
for (label, vals), color, marker in zip(impr.items(), line_colors, markers):
    lw = 1.2 if label == 'Shifting (secondary)' else 2
    ls = '--' if label == 'Shifting (secondary)' else '-'
    ax.plot(all_gammas, vals, marker + ls, color=color, linewidth=lw,
            markersize=5, label=label)

ax.axhline(0, color='black', linewidth=0.8, linestyle='--', alpha=0.5)
ax.axvline(0.75, color='gray', linewidth=1.0, linestyle=':', alpha=0.7)
ymin, ymax = ax.get_ylim()
ax.text(0.76, ymin + (ymax - ymin) * 0.02, 'γ=0.75\n(recommended)',
        fontsize=9, color='gray', va='bottom')
ax.set_xlabel('Emission weight γ')
ax.set_ylabel('Improvement over FCFS (%)')
ax.set_title('GA Trade-off Across Emission Weight γ\n(positive = GA better than FCFS)',
             fontweight='bold')
ax.set_xticks(all_gammas)
ax.set_xticklabels([f'{g:.2f}' for g in all_gammas])
ax.legend(loc='center right', framealpha=0.9, fontsize=10)
plt.tight_layout()
plt.savefig('fig2_tradeoff_lines.png')
plt.close()
print("Saved fig2_tradeoff_lines.png")


# ── Figure 3: Radar chart — 3 objective criteria + shifting as secondary ──────
def norm_inv(val, ref):
    return max(0.0, 1.0 - val / ref)


radar_entries = {
    'FCFS': baselines['FCFS'],
    'EDD': baselines['EDD'],
    'GA γ=0.00': next((s, f, d, e) for g, s, f, d, e, z in ga_rows if g == 0.00),
    'GA γ=0.50': next((s, f, d, e) for g, s, f, d, e, z in ga_rows if g == 0.50),
    'GA γ=0.75': next((s, f, d, e) for g, s, f, d, e, z in ga_rows if g == 0.75),
    'GA γ=1.00': next((s, f, d, e) for g, s, f, d, e, z in ga_rows if g == 1.00),
}
radar_colors = [GRAY, CORAL, '#93b8e0', '#5b8fcc', BLUE, '#1a3f75']
categories = ['Fatigue', 'Delay', 'Emissions', 'Shifting*']
refs = [F_REF, D_REF, E_REF / 1000, 300]
N = len(categories)
angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist() + [0]

fig, ax = plt.subplots(figsize=(7, 7), subplot_kw=dict(polar=True))
for (name, data), color in zip(radar_entries.items(), radar_colors):
    s, f, d, e = data
    vals = [norm_inv(f, refs[0]), norm_inv(d, refs[1]),
            norm_inv(e / 1000, refs[2]), norm_inv(s, refs[3])] + [0]
    vals[-1] = vals[0]
    lw = 2.5 if 'GA' in name else 1.5
    ls = '-' if 'GA' in name else '--'
    ax.plot(angles, vals, color=color, linewidth=lw, linestyle=ls, label=name)
    ax.fill(angles, vals, color=color, alpha=0.05)

ax.set_xticks(angles[:-1])
ax.set_xticklabels(categories, fontsize=11)
ax.set_ylim(0, 1)
ax.set_title('Normalised performance (higher = better)\n*Shifting reported as secondary metric',
             fontweight='bold', pad=20)
ax.legend(loc='upper right', bbox_to_anchor=(1.4, 1.15), fontsize=9)
plt.tight_layout()
plt.savefig('fig3_radar.png')
plt.close()
print("Saved fig3_radar.png")