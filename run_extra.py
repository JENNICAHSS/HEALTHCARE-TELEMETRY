#!/usr/bin/env python3
"""Additional experiments: ARQ-only ablation (no FEC / alarm copies) and backhaul-delay sweep."""
import csv, time
from multiprocessing import Pool
from sim import run_one, SCHEMES

import sys
SEEDS = list(range(1, (int(sys.argv[1]) if len(sys.argv) > 1 else 8) + 1))

def job(a):
    exp, val, label, scheme, kw, seed = a
    return exp, val, label, seed, run_one(scheme, seed, **kw)

if __name__ == '__main__':
    jobs = []
    for k in [0, 2, 4, 8, 12, 16]:
        for seed in SEEDS:
            jobs.append(('K', k, 'Proposed (no FEC)', 'Proposed', {'K': k, 'use_fec': False}, seed))
    for d in [10, 40, 80, 120]:
        for s in SCHEMES:
            for seed in SEEDS:
                jobs.append(('d', d, s, s, {'prop': d}, seed))
        for seed in SEEDS:
            jobs.append(('d', d, 'Proposed (no FEC)', 'Proposed', {'prop': d, 'use_fec': False}, seed))
    print(len(jobs), 'runs', flush=True)
    t0 = time.time()
    with open('results_extra.csv', 'w', newline='') as f, Pool(2) as p:
        w = None
        for i, (exp, val, label, seed, r) in enumerate(p.imap_unordered(job, jobs, chunksize=2)):
            row = {'exp': exp, 'value': val, 'scheme': label, 'seed': seed}
            row.update({k: v for k, v in r.items() if not k.startswith('_')})
            if w is None:
                w = csv.DictWriter(f, fieldnames=list(row.keys())); w.writeheader()
            w.writerow(row); f.flush()
            if i % 50 == 0:
                print(i, '/', len(jobs), '%.0fs' % (time.time() - t0), flush=True)
    print('done %.0fs' % (time.time() - t0), flush=True)
