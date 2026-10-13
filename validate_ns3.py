#!/usr/bin/env python3
"""Compare the Python 802.11g DCF replica (sim_wifi.py) with the ns-3 results from the repository
(data/ns3_results.csv). Writes figs/fig_validation.pdf|png and validation.json."""
import csv, json, math, os, sys
import numpy as np
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from sim_wifi import run_wifi

HERE = os.path.dirname(os.path.abspath(__file__))
SEEDS = int(sys.argv[1]) if len(sys.argv) > 1 else 30
rows = list(csv.DictReader(open(os.path.join(HERE, 'data/ns3_results.csv'))))
ns3 = {(int(r['Background_Load_Mbps']), r['Protocol'].lower()): r for r in rows}

def ci(v):
    v = np.asarray(v, float)
    return v.mean(), (stats.t.ppf(0.975, len(v) - 1) * v.std(ddof=1) / math.sqrt(len(v)) if len(v) > 1 else 0)

out = {}
for p in ('udp', 'tcp'):
    for l in (1, 4, 8):
        rs = [run_wifi(p, l, s) for s in range(1, SEEDS + 1)]
        d = {}
        for key, f, fl in (('hc_thr', 'thr_kbps', 'hc'), ('hc_delay', 'delay_ms', 'hc'), ('hc_jitter', 'jitter_ms', 'hc'),
                           ('hc_lost', 'lost', 'hc'), ('bg_thr', 'thr_kbps', 'bg'), ('bg_delay', 'delay_ms', 'bg'),
                           ('bg_lost', 'lost', 'bg')):
            m, c = ci([r[fl][f] for r in rs])
            d[key] = [m, c]
        d['hc_delay_med'] = float(np.median([r['hc']['delay_ms'] for r in rs]))
        n = ns3[(l, p)]
        d['ns3'] = dict(hc_thr=float(n['Healthcare_Throughput_kbps']), hc_delay=float(n['Healthcare_Delay_ms']),
                        hc_jitter=float(n['Healthcare_Jitter_ms']), hc_lost=float(n['Healthcare_Lost']),
                        bg_thr=float(n['Background_Throughput_kbps']), bg_delay=float(n['Background_Delay_ms']),
                        bg_lost=float(n['Background_Tx']) - float(n['Background_Rx']))
        out['%s|%d' % (p, l)] = d
json.dump(out, open(os.path.join(HERE, 'validation.json'), 'w'), indent=1)

plt.rcParams.update({'font.size': 8, 'font.family': 'serif', 'axes.grid': True, 'grid.alpha': .3})
panels = [('hc_thr', 'Healthcare throughput (kbit/s)', False), ('hc_delay', 'Healthcare delay (ms)', False),
          ('hc_jitter', 'Healthcare jitter (ms)', False), ('bg_delay', 'Background delay (ms, log)', True)]
fig, axs = plt.subplots(1, 4, figsize=(7.2, 2.1))
col = {'udp': '#1f77b4', 'tcp': '#d95f02'}
for ax, (k, lab, lg) in zip(axs, panels):
    for p in ('udp', 'tcp'):
        xs = [1, 4, 8]
        ax.plot(xs, [out['%s|%d' % (p, l)]['ns3'][k] for l in xs], 'o-', color=col[p], lw=1.4, ms=4)
        m = [out['%s|%d' % (p, l)][k][0] for l in xs]; c = [out['%s|%d' % (p, l)][k][1] for l in xs]
        ax.errorbar([x + (.12 if p == 'tcp' else -.12) for x in xs], m, yerr=c, fmt='s--', mfc='white', color=col[p], lw=1, ms=4, capsize=2)
    ax.set_xticks([1, 4, 8]); ax.set_xlabel('Background load (Mbit/s)'); ax.set_title(lab, fontsize=7.5)
    if lg: ax.set_yscale('log')
from matplotlib.lines import Line2D
h = [Line2D([], [], color=col['udp'], marker='o'), Line2D([], [], color=col['tcp'], marker='o'),
     Line2D([], [], color='k', marker='o'), Line2D([], [], color='k', marker='s', mfc='white', ls='--')]
fig.legend(h, ['UDP', 'TCP', 'ns-3 (repository, 1 run)', 'Python replica (mean$\\pm$95% CI)'], loc='lower center', ncol=4, frameon=False, fontsize=7.5)
fig.tight_layout(rect=(0, .1, 1, 1))
fig.savefig(os.path.join(HERE, 'figs/fig_validation.pdf')); fig.savefig(os.path.join(HERE, 'figs/fig_validation.png'), dpi=200)
print('ok')
