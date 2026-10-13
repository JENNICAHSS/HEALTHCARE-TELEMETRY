#!/usr/bin/env python3
"""Run all experiments and write results.csv (one row per run) and cdf.pkl."""
import csv, pickle, sys, time
from multiprocessing import Pool
from sim import run_one, SCHEMES, DEFAULTS

import sys
SEEDS = list(range(1, (int(sys.argv[1]) if len(sys.argv) > 1 else 8) + 1))
EXPS = {
    'K':        ('K',        [0, 2, 4, 8, 12, 16], {}),
    'N':        ('N',        [20, 40, 60, 80, 100, 120], {}),
    'loss_bad': ('loss_bad', [0.05, 0.15, 0.25, 0.40, 0.55], {'K': 4}),
    'buf':      ('buf',      [25000, 50000, 100000, 200000, 400000], {}),
}

def overrides(exp, val, base):
    kw = dict(base)
    if exp == 'buf':
        kw['buf_fifo'] = val
        kw['buf_prio'] = (10000, 30000, 10000, val)
    else:
        kw[EXPS[exp][0]] = val
    return kw

def job(a):
    exp, val, label, scheme, extra, seed, kw = a
    kw = dict(kw); kw.update(extra)
    r = run_one(scheme, seed, **kw)
    return exp, val, label, seed, r

if __name__ == '__main__':
    jobs = []
    for exp, (_, vals, base) in EXPS.items():
        for v in vals:
            kw = overrides(exp, v, base)
            for s in SCHEMES:
                for seed in SEEDS:
                    jobs.append((exp, v, s, s, {}, seed, kw))
            if exp == 'N':
                for seed in SEEDS:
                    jobs.append((exp, v, 'Proposed (no gating)', 'Proposed', {'fec_gate': False}, seed, kw))
    print(len(jobs), 'runs', flush=True)
    t0 = time.time()
    fields = None
    with open('results.csv', 'w', newline='') as f, Pool(2) as p:
        w = None
        for i, (exp, val, label, seed, r) in enumerate(p.imap_unordered(job, jobs, chunksize=2)):
            row = {'exp': exp, 'value': val, 'scheme': label, 'seed': seed}
            row.update({k: v for k, v in r.items() if not k.startswith('_')})
            if w is None:
                w = csv.DictWriter(f, fieldnames=list(row.keys())); w.writeheader()
            w.writerow(row); f.flush()
            if i % 50 == 0:
                print(i, '/', len(jobs), '%.0fs' % (time.time() - t0), flush=True)
    # latency distributions for the default congested scenario
    cdf = {}
    for s in SCHEMES:
        cdf[s] = [run_one(s, seed, keep_lat=True)['_lat'] for seed in (1, 2, 3)]
    pickle.dump(cdf, open('cdf.pkl', 'wb'))
    print('done %.0fs' % (time.time() - t0), flush=True)
