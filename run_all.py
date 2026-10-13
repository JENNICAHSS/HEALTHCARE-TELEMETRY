#!/usr/bin/env python3
"""Regenerate every result in the paper.
   python run_all.py --quick     # ~2 minutes, 2 seeds
   python run_all.py             # full set, 8 seeds (about 1.5 hours on 2 cores)"""
import sys, subprocess
quick = '--quick' in sys.argv
seeds = '2' if quick else '8'
subprocess.check_call([sys.executable, 'validate_ns3.py', '10' if quick else '30'])
subprocess.check_call([sys.executable, 'run_experiments.py', seeds])
subprocess.check_call([sys.executable, 'run_extra.py', seeds])
subprocess.check_call([sys.executable, 'analyze.py'])
print('done: see results.csv, results_extra.csv, summary.json and figs/')
