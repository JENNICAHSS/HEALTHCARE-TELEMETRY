# Transport-layer optimization for real-time healthcare telemetry - working model

Python model, interactive demo and reproducible experiments behind the paper and slides.

## Quick start
    pip install numpy scipy matplotlib pandas streamlit
    streamlit run app.py            # interactive demo (opens in the browser)
    python run_all.py --quick       # regenerate every number and figure in ~2 minutes
    python run_all.py               # full run, 8 seeds

## Files
| File | Purpose |
|---|---|
| `app.py` | Streamlit demo: live comparison, parameter sweeps, ns-3 validation, explanation |
| `sim.py` | Main model: bursty-loss wireless bottleneck, TCP / UDP / UDP+Prio / Transport-only / Proposed |
| `sim_wifi.py` | Validation model: 802.11g DCF replica of the ns-3 scenario in the base repository |
| `validate_ns3.py` | Compares the replica with `data/ns3_results.csv` (ns-3 output from the repository) |
| `run_experiments.py`, `run_extra.py`, `analyze.py` | Full experiment grid, extra ablations, figures, `summary.json` |
| `results*.csv`, `summary.json`, `validation.json` | Raw per-run and summarised results used in the paper |

## Base repository
`data/ns3_results.csv` is the output of https://github.com/nikhilsamsonsuresh-sketch/healthcare-telemetry-ns3
(NS-3.47, TCP vs UDP at 1/4/8 Mbit/s background load). That repository's ns-3 code is the baseline experiment;
the Python models extend it. All results here come from simulation, not from real medical devices.
