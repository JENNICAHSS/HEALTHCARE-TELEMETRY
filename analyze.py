import csv, json, pickle, math
from collections import defaultdict
import numpy as np
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

plt.rcParams.update({
    'font.family': 'serif', 'font.serif': ['Times New Roman', 'Liberation Serif', 'DejaVu Serif'],
    'font.size': 7.5, 'axes.labelsize': 7.5, 'legend.fontsize': 6.3, 'xtick.labelsize': 7, 'ytick.labelsize': 7,
    'axes.linewidth': 0.6, 'lines.linewidth': 1.2, 'lines.markersize': 3.6,
    'axes.grid': True, 'grid.alpha': 0.3, 'grid.linewidth': 0.4,
})
SCHEMES = ['TCP', 'UDP', 'UDP+Prio', 'Transport-only', 'Proposed']
STYLE = {  # Okabe-Ito
    'TCP': ('#D55E00', 'o', '-'), 'UDP': ('#E69F00', 's', '-'), 'UDP+Prio': ('#56B4E9', '^', '-'),
    'Transport-only': ('#009E73', 'D', '-'), 'Proposed': ('#000000', '*', '-'),
    'Proposed (no gating)': ('#CC79A7', 'v', '--'),
    'Proposed (no FEC)': ('#0072B2', 'x', '--'),
}

rows = list(csv.DictReader(open('results.csv'))) + list(csv.DictReader(open('results_extra.csv')))
data = defaultdict(lambda: defaultdict(list))   # (exp,value,scheme) -> metric -> list
for r in rows:
    key = (r['exp'], float(r['value']), r['scheme'])
    for k, v in r.items():
        if k in ('exp', 'value', 'scheme', 'seed'):
            continue
        data[key][k].append(float(v))

def ms(exp, val, scheme, metric):
    xs = [x for x in data[(exp, float(val), scheme)][metric] if not math.isnan(x)]
    n = len(xs)
    if n == 0:
        return float('nan'), float('nan'), 0
    m = float(np.mean(xs))
    ci = float(stats.t.ppf(0.975, n - 1) * np.std(xs, ddof=1) / math.sqrt(n)) if n > 1 else 0.0
    return m, ci, n

def series(exp, vals, scheme, metric):
    m = [ms(exp, v, scheme, metric) for v in vals]
    return np.array([a[0] for a in m]), np.array([a[1] for a in m])

VALS = {'K': [0, 2, 4, 8, 12, 16], 'N': [20, 40, 60, 80, 100, 120],
        'loss_bad': [0.05, 0.15, 0.25, 0.40, 0.55], 'buf': [25000, 50000, 100000, 200000, 400000],
        'd': [10, 40, 80, 120]}

def plot_panel(ax, exp, metric, ylabel, schemes, xs=None, scale=1.0, logy=False, xlabel=None, ylim=None):
    vals = VALS[exp]
    x = np.array(xs if xs is not None else vals, dtype=float)
    for s in schemes:
        c, mk, ls = STYLE[s]
        m, ci = series(exp, vals, s, metric)
        ax.errorbar(x, m * scale, yerr=ci * scale, color=c, marker=mk, ls=ls, label=s, capsize=1.5, elinewidth=0.6,
                    markersize=5.5 if mk == '*' else 3.6)
    ax.set_ylabel(ylabel)
    if xlabel: ax.set_xlabel(xlabel)
    if logy: ax.set_yscale('log')
    if ylim: ax.set_ylim(*ylim)

def add_legend(fig, ax, ncol=None):
    h, l = ax.get_legend_handles_labels()
    fig.legend(h, l, loc='upper center', bbox_to_anchor=(0.5, -0.02), ncol=ncol or len(l), frameon=False, columnspacing=1.2, handlelength=2.0)

def save(fig, name):
    fig.savefig('figs/%s.pdf' % name, bbox_inches='tight', pad_inches=0.03)
    fig.savefig('figs/%s.png' % name, dpi=220, bbox_inches='tight', pad_inches=0.03)
    plt.close(fig)

# ---- Fig 2: timely delivery vs congestion level
fig, axs = plt.subplots(1, 3, figsize=(7.16, 2.15))
plot_panel(axs[0], 'K', 'tdr_alarm', 'Timely delivery ratio, alarms (%)', SCHEMES, scale=100, xlabel='Background bulk flows (K)', ylim=(-3, 103))
plot_panel(axs[1], 'K', 'tdr_ecg', 'Timely delivery ratio, ECG (%)', SCHEMES, scale=100, xlabel='Background bulk flows (K)', ylim=(-3, 103))
plot_panel(axs[2], 'K', 'p99_ecg', '99th-pct ECG latency (ms)', SCHEMES, logy=True, xlabel='Background bulk flows (K)')
axs[2].axhline(300, color='gray', ls=':', lw=0.8); axs[2].text(0.3, 330, 'ECG deadline', fontsize=6, color='gray')
for a, t in zip(axs, '(a) (b) (c)'.split()):
    a.set_title(t, fontsize=7.5, y=-0.42)
fig.tight_layout(w_pad=1.0)
add_legend(fig, axs[0])
save(fig, 'fig_k')

# ---- Fig 3: latency CDFs in default scenario
cdf = pickle.load(open('cdf.pkl', 'rb'))
fig, axs = plt.subplots(1, 2, figsize=(7.16, 2.2))
for ax, cls, dl, ttl in [(axs[0], 'alarm', 150, '(a) Alarm messages'), (axs[1], 'ecg', 300, '(b) ECG messages')]:
    for s in SCHEMES:
        c, mk, ls = STYLE[s]
        lat = np.sort(np.concatenate([np.array(d[cls]) for d in cdf[s]]))
        ytot = sum(1 for _ in lat)
        # empirical CDF over delivered messages; undelivered shown by plateau below 1
        tot = 0
        # total generated count (3 seeds)
        # approximate with delivered + undelivered stored in results? use delivered only here, and annotate in caption
        y = np.arange(1, len(lat) + 1) / len(lat)
        ax.plot(lat, y, color=c, ls=ls, label=s, lw=1.4 if s == 'Proposed' else 1.1)
    ax.axvline(dl, color='gray', ls=':', lw=0.9)
    ax.set_xscale('log'); ax.set_xlim(8, 12000); ax.set_ylim(0, 1.02)
    ax.set_xlabel('End-to-end latency (ms, log scale)'); ax.set_ylabel('CDF (delivered messages)')
    ax.set_title(ttl, fontsize=7.5, y=-0.38)
fig.tight_layout(w_pad=1.2)
add_legend(fig, axs[0])
save(fig, 'fig_cdf')

# ---- Fig 4: scalability
fig, axs = plt.subplots(1, 3, figsize=(7.16, 2.15))
S2 = SCHEMES + ['Proposed (no gating)']
plot_panel(axs[0], 'N', 'tdr_all', 'Timely delivery ratio, all (%)', S2, scale=100, xlabel='Monitored patients (N)', ylim=(-3, 103))
plot_panel(axs[1], 'N', 'tdr_vital', 'Timely delivery ratio, vitals (%)', S2, scale=100, xlabel='Monitored patients (N)', ylim=(-3, 103))
plot_panel(axs[2], 'N', 'bulk_mbps', 'Background goodput (Mbit/s)', SCHEMES, xlabel='Monitored patients (N)')
for a, t in zip(axs, '(a) (b) (c)'.split()):
    a.set_title(t, fontsize=7.5, y=-0.42)
fig.tight_layout(w_pad=1.0)
add_legend(fig, axs[0])
save(fig, 'fig_n')

# ---- Fig 5: loss and buffer sensitivity
fig, axs = plt.subplots(1, 3, figsize=(7.16, 2.15))
plot_panel(axs[0], 'loss_bad', 'tdr_ecg', 'Timely delivery ratio, ECG (%)', SCHEMES, scale=100, xs=[100 * v for v in VALS['loss_bad']], xlabel='Bad-state loss probability (%)', ylim=(-3, 103))
plot_panel(axs[1], 'loss_bad', 'tdr_alarm', 'Timely delivery ratio, alarms (%)', SCHEMES, scale=100, xs=[100 * v for v in VALS['loss_bad']], xlabel='Bad-state loss probability (%)', ylim=(-3, 103))
plot_panel(axs[2], 'buf', 'tdr_alarm', 'Timely delivery ratio, alarms (%)', SCHEMES, scale=100, xs=[v / 1000 for v in VALS['buf']], xlabel='Bottleneck buffer (kB)', ylim=(-3, 103))
axs[2].set_xscale('log'); axs[2].set_xticks([25, 50, 100, 200, 400]); axs[2].set_xticklabels(['25', '50', '100', '200', '400'])
from matplotlib.ticker import NullLocator
axs[2].xaxis.set_minor_locator(NullLocator())
for a, t in zip(axs, '(a) (b) (c)'.split()):
    a.set_title(t, fontsize=7.5, y=-0.42)
fig.tight_layout(w_pad=1.0)
add_legend(fig, axs[0])
save(fig, 'fig_sens')

# ---- Fig 6: backhaul delay sweep
fig, axs = plt.subplots(1, 3, figsize=(7.16, 2.15))
SD = SCHEMES + ['Proposed (no FEC)']
plot_panel(axs[0], 'd', 'tdr_alarm', 'Timely delivery ratio, alarms (%)', SD, scale=100, xlabel='One-way backhaul delay d (ms)', ylim=(-3, 103))
plot_panel(axs[1], 'd', 'tdr_ecg', 'Timely delivery ratio, ECG (%)', SD, scale=100, xlabel='One-way backhaul delay d (ms)', ylim=(-3, 103))
plot_panel(axs[2], 'd', 'overhead', 'Overhead ratio O', ['Proposed', 'Proposed (no FEC)', 'Transport-only'], xlabel='One-way backhaul delay d (ms)')
for a, t in zip(axs, '(a) (b) (c)'.split()):
    a.set_title(t, fontsize=7.5, y=-0.42)
fig.tight_layout(w_pad=1.0)
add_legend(fig, axs[0])
save(fig, 'fig_d')

# ---- numbers for tables / text
summary = {}
for exp, vals in VALS.items():
    for v in vals:
        for s in SCHEMES + (['Proposed (no gating)'] if exp == 'N' else []) + (['Proposed (no FEC)'] if exp in ('K', 'd') else []):
            d = {}
            for metric in data[(exp, float(v), s)]:
                m, ci, n = ms(exp, v, s, metric)
                d[metric] = [m, ci]
            d['n'] = ms(exp, v, s, 'tdr_all')[2]
            summary['%s|%s|%s' % (exp, v, s)] = d
json.dump(summary, open('summary.json', 'w'), indent=1)
print('ok', len(summary))
