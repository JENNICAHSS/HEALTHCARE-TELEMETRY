"""Interactive demo: run with   streamlit run app.py
Compares TCP, UDP, UDP+Prio, Transport-only and Proposed for deadline-bound healthcare telemetry."""
import os, csv
import numpy as np
import pandas as pd
import streamlit as st
import sim
from sim_wifi import run_wifi

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMES = sim.SCHEMES
st.set_page_config(page_title="Healthcare telemetry transport demo", layout="wide")
st.title("Transport-layer optimization for real-time healthcare telemetry")
st.caption("Simulation model - not a measurement of a physical network. Deadlines (alarm 150 ms, ECG 300 ms, vitals 1 s) are design assumptions.")

tab1, tab2, tab3, tab4 = st.tabs(["Live comparison", "Parameter sweep", "Validation vs ns-3", "How it works"])

with st.sidebar:
    st.header("Scenario")
    N = st.slider("Monitored patients (N)", 10, 120, 40, 10)
    K = st.slider("Background bulk TCP flows (K)", 0, 16, 8)
    lbad = st.slider("Bad-state packet loss (%)", 5, 55, 25) / 100
    buf = st.select_slider("Bottleneck buffer (kB)", [25, 50, 100, 200, 400], 200)
    delay = st.select_slider("One-way delay (ms)", [10, 40, 80, 120], 10)
    seconds = st.slider("Simulated seconds", 20, 65, 30, 5)
    seeds = st.slider("Runs per scheme", 1, 5, 2)
    st.caption("More patients, flows and runs = slower. Defaults finish in a few seconds.")

def overrides():
    T = seconds * 1000
    return dict(N=N, K=K, loss_bad=lbad, buf_fifo=buf * 1000,
                buf_prio=(10000, 30000, 10000, buf * 1000), prop=delay, T=T,
                warm=min(5000, T // 5), tail=min(3000, T // 10))

def agg(rs, k):
    return float(np.mean([r[k] for r in rs]))

with tab1:
    if st.button("Run all five schemes", type="primary"):
        res = {}
        prog = st.progress(0.0)
        for i, s in enumerate(SCHEMES):
            res[s] = [sim.run_one(s, sd, False, **overrides()) for sd in range(1, seeds + 1)]
            prog.progress((i + 1) / len(SCHEMES))
        st.session_state['res'] = res
    res = st.session_state.get('res')
    if res:
        df = pd.DataFrame({s: {
            "Alarms on time (%)": 100 * agg(r, 'tdr_alarm'), "ECG on time (%)": 100 * agg(r, 'tdr_ecg'),
            "Vitals on time (%)": 100 * agg(r, 'tdr_vital'), "p99 alarm latency (ms)": agg(r, 'p99_alarm'),
            "p99 ECG latency (ms)": agg(r, 'p99_ecg'), "Overhead ratio": agg(r, 'overhead'),
            "Bulk goodput (Mbit/s)": agg(r, 'bulk_mbps')} for s, r in res.items()}).T
        c1, c2, c3 = st.columns(3)
        c1.metric("Alarms on time - TCP", f"{df.loc['TCP', 'Alarms on time (%)']:.1f}%")
        c2.metric("Alarms on time - Proposed", f"{df.loc['Proposed', 'Alarms on time (%)']:.1f}%")
        c3.metric("Bulk goodput cost vs UDP+Prio",
                  f"{100 * (1 - df.loc['Proposed', 'Bulk goodput (Mbit/s)'] / df.loc['UDP+Prio', 'Bulk goodput (Mbit/s)']):.0f}%")
        a, b = st.columns(2)
        a.subheader("Delivered by deadline (%)")
        a.bar_chart(df[["Alarms on time (%)", "ECG on time (%)", "Vitals on time (%)"]])
        b.subheader("99th-percentile latency (ms)")
        b.bar_chart(df[["p99 alarm latency (ms)", "p99 ECG latency (ms)"]])
        st.dataframe(df.style.format("{:.2f}"), use_container_width=True)
    else:
        st.info("Set the scenario in the sidebar, then press the button.")

with tab2:
    param = st.selectbox("Sweep", ["Background flows K", "Patients N", "Bad-state loss"])
    vals = {"Background flows K": [0, 4, 8, 12, 16], "Patients N": [20, 40, 60, 80, 100],
            "Bad-state loss": [0.05, 0.15, 0.25, 0.4, 0.55]}[param]
    key = {"Background flows K": "K", "Patients N": "N", "Bad-state loss": "loss_bad"}[param]
    metric = st.selectbox("Metric", ["Alarms on time (%)", "ECG on time (%)", "Vitals on time (%)"])
    mk = {"Alarms on time (%)": "tdr_alarm", "ECG on time (%)": "tdr_ecg", "Vitals on time (%)": "tdr_vital"}[metric]
    chosen = st.multiselect("Schemes", SCHEMES, default=["TCP", "UDP+Prio", "Proposed"])
    if st.button("Run sweep"):
        out = pd.DataFrame(index=vals, columns=chosen, dtype=float)
        prog = st.progress(0.0); n = 0
        for v in vals:
            for s in chosen:
                o = overrides(); o[key] = v
                if key == "loss_bad":
                    o["loss_bad"] = v
                rs = [sim.run_one(s, sd, False, **o) for sd in range(1, seeds + 1)]
                out.loc[v, s] = 100 * agg(rs, mk)
                n += 1; prog.progress(n / (len(vals) * len(chosen)))
        st.line_chart(out)
        st.dataframe(out.style.format("{:.1f}"))

with tab3:
    st.write("The repository's ns-3 experiment (802.11g at 6 Mbit/s, one healthcare station, one background station) "
             "versus the Python replica used as the validation model.")
    ns3 = pd.read_csv(os.path.join(HERE, "data", "ns3_results.csv"))
    st.subheader("ns-3 results (from the repository)")
    st.dataframe(ns3[["Background_Load_Mbps", "Protocol", "Healthcare_Throughput_kbps", "Healthcare_Delay_ms",
                      "Healthcare_Jitter_ms", "Healthcare_Lost", "Background_Throughput_kbps", "Background_Delay_ms"]],
                 use_container_width=True)
    c1, c2, c3 = st.columns(3)
    proto = c1.selectbox("Protocol", ["udp", "tcp"])
    load = c2.select_slider("Background load (Mbit/s)", [1, 2, 4, 6, 8, 10], 8)
    runs = c3.slider("Runs", 1, 30, 10)
    if st.button("Run Wi-Fi replica"):
        rs = [run_wifi(proto, load, s) for s in range(1, runs + 1)]
        m = lambda f, k: float(np.mean([r[f][k] for r in rs]))
        st.table(pd.DataFrame({
            "Healthcare throughput (kbit/s)": [m('hc', 'thr_kbps')], "Healthcare delay (ms)": [m('hc', 'delay_ms')],
            "Healthcare jitter (ms)": [m('hc', 'jitter_ms')], "Healthcare lost": [m('hc', 'lost')],
            "Background throughput (kbit/s)": [m('bg', 'thr_kbps')], "Background delay (ms)": [m('bg', 'delay_ms')]}).round(2))
    fig = os.path.join(HERE, "figs", "fig_validation.png")
    if os.path.exists(fig):
        st.image(fig, caption="ns-3 (filled) vs Python replica (open, mean and 95% CI over 30 runs)")

with tab4:
    st.markdown("""
**Problem.** Patient monitors send small deadline-bound messages (alarm 150 ms, ECG 300 ms, vitals 1 s) over a shared wireless network
where bulk TCP traffic fills the access-point queue. TCP's in-order delivery and long retransmission timer turn single losses and deep queues into
missed deadlines; UDP has no recovery.

**Proposed framework (four cooperating mechanisms).**
1. *Per-class streams* - messages are classified (alarm / ECG / vitals) and delivered out of order, so one loss never blocks later messages.
2. *Deadline-aware selective ARQ* - RTO = max(30 ms, srtt + 4 rttvar); retransmit only if `r < 3` and `t + srtt/2 <= deadline`.
3. *Loss-adaptive FEC with a congestion gate* - XOR parity every 4 or 2 ECG packets as the loss estimate rises; a second alarm copy after 10 ms; **all redundancy is disabled when
the smoothed RTT shows queueing** (`srtt_ECG > 1.5 (2d + 4 ms)`), so protection never worsens congestion.
4. *Priority queue with deadline-aware dropping* - telemetry bypasses bulk traffic; expired packets are dropped at dequeue instead of being sent late.

Results come from a simulation; see the paper for limits.
""")
