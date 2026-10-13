#!/usr/bin/env python3
"""
Discrete-time (1 ms) simulation of real-time healthcare telemetry over a congested,
bursty-loss wireless bottleneck.  Five transport configurations are compared:

  TCP             Reno-style TCP with SACK-based recovery, one connection per patient
                  device (MQTT-over-TCP style), FIFO bottleneck queue
  UDP             plain UDP datagrams, no recovery, FIFO queue
  UDP+Prio        UDP with class-based strict-priority queueing at the access point
  Transport-only  proposed end-host mechanisms (deadline-aware selective ARQ, adaptive
                  FEC / alarm redundancy, out-of-order delivery) over a FIFO queue
  Proposed        Transport-only + priority queueing + deadline-aware queue dropping

Everything here is a simulation model; numbers it produces are not measurements of a
physical network.
"""
import heapq
import random
import math
import sys
import csv
import time
from collections import deque, defaultdict

HDR = 40
MSS = 1500
ALARM, ECG, VITAL, BULK = 0, 1, 2, 3
PAYLOAD = {ALARM: 60, ECG: 200, VITAL: 80}
PERIOD = {ECG: 40, VITAL: 1000}
DEADLINE = {ALARM: 150, ECG: 300, VITAL: 1000}
ALARM_MEAN_MS = 5000
CLS_NAME = {ALARM: 'alarm', ECG: 'ecg', VITAL: 'vital'}

DEFAULTS = dict(
    N=40, K=8, T=65000, warm=5000, tail=3000,
    cap_good=1000.0, cap_bad=600.0,          # bytes per ms  (8 Mbit/s / 4.8 Mbit/s)
    p_gb=1 / 700.0, p_bg=1 / 40.0,           # Gilbert-Elliott transition probs per ms
    loss_good=0.005, loss_bad=0.25,
    prop=10,                                  # one-way propagation / backhaul delay (ms)
    buf_fifo=200000, buf_prio=(10000, 30000, 10000, 200000),
    use_fec=True,                             # False: ARQ only (no parity, no alarm copies)
    ack_loss=True,                            # ACKs suffer the same channel loss as data
    fec_gate=True,                            # congestion-aware gating of FEC / alarm copies
)

SCHEMES = ['TCP', 'UDP', 'UDP+Prio', 'Transport-only', 'Proposed']
SCHEME_CFG = {  # transport, priority queue, deadline-aware queue drop
    'TCP': ('tcp', False, False),
    'UDP': ('udp', False, False),
    'UDP+Prio': ('udp', True, False),
    'Transport-only': ('prop', False, False),
    'Proposed': ('prop', True, True),
}

E_ARR, E_TACK, E_PACK, E_PRTO, E_COPY = range(5)


class Pkt:
    __slots__ = ('kind', 'pid', 'cls', 'seq', 'size', 'gen', 'dl', 'sent', 'tries',
                 'gstart', 'g', 'conn', 'rtt_ok')

    def __init__(self, kind, cls, seq, size, gen, dl, pid=None, conn=None):
        self.kind = kind; self.cls = cls; self.seq = seq; self.size = size
        self.gen = gen; self.dl = dl; self.pid = pid; self.conn = conn
        self.sent = 0; self.tries = 0; self.gstart = None; self.g = 0; self.rtt_ok = True


class Link:
    def __init__(self, P, prio, ddl_drop, rng, sim):
        self.P = P; self.prio = prio; self.ddl = ddl_drop; self.rng = rng; self.sim = sim
        nq = 4 if prio else 1
        self.q = [deque() for _ in range(nq)]
        self.qb = [0] * nq
        self.lim = list(P['buf_prio']) if prio else [P['buf_fifo']]
        self.credit = 0.0
        self.bad = False
        self.offered_tel = 0
        self.drops_q = defaultdict(int)
        self.drops_l = defaultdict(int)
        self.drops_d = defaultdict(int)

    def enqueue(self, p):
        if p.cls != BULK:
            self.offered_tel += p.size
        qi = p.cls if self.prio else 0
        if self.qb[qi] + p.size > self.lim[qi]:
            self.drops_q[p.cls] += 1
            return
        self.q[qi].append(p)
        self.qb[qi] += p.size

    def step(self, t):
        P = self.P; rng = self.rng
        if self.bad:
            if rng.random() < P['p_bg']:
                self.bad = False
        elif rng.random() < P['p_gb']:
            self.bad = True
        cap = P['cap_bad'] if self.bad else P['cap_good']
        lp = P['loss_bad'] if self.bad else P['loss_good']
        self.credit += cap
        prop = P['prop']
        while True:
            qi = -1
            for i, dq in enumerate(self.q):
                if dq:
                    qi = i
                    break
            if qi < 0:
                if self.credit > 1500.0:
                    self.credit = 1500.0
                break
            head = self.q[qi][0]
            if self.ddl and head.cls != BULK and t + prop > head.dl:
                self.q[qi].popleft(); self.qb[qi] -= head.size
                self.drops_d[head.cls] += 1
                continue
            if self.credit < head.size:
                break
            self.q[qi].popleft(); self.qb[qi] -= head.size
            self.credit -= head.size
            if rng.random() < lp:
                self.drops_l[head.cls] += 1
            else:
                self.sim.push(t + prop, E_ARR, head)


class Conn:
    """TCP Reno-style sender/receiver pair with SACK-based hole retransmission."""

    def __init__(self, sim, bulk, pid=None, start=0):
        self.sim = sim; self.bulk = bulk; self.pid = pid; self.start = start
        self.cwnd = 10.0; self.ssthresh = 1e9
        self.una = 0; self.nxt = 0
        self.msgs = []
        self.srtt = None; self.rttvar = 0.0; self.rto = 1000.0
        self.rto_at = None; self.backoff = 1
        self.dup = 0; self.rec = False; self.recover = 0
        self.sacked = set(); self.marked = set(); self.retx_q = deque()
        self.sent_t = {}
        self.rcv_nxt = 0; self.ooo = set(); self.deliv = {}
        self.una_warm = 0; self.una_end = 0

    # ---------------- sender ----------------
    def has_new(self):
        return True if self.bulk else self.nxt < len(self.msgs)

    def try_send(self, t):
        if t < self.start:
            return
        while True:
            outstanding = self.nxt - self.una - len(self.sacked)
            pipe = outstanding - len(self.retx_q)
            if pipe >= int(self.cwnd):
                break
            if self.retx_q:
                seq = self.retx_q.popleft()
                if seq < self.una or seq in self.sacked:
                    continue
                self._tx(t, seq, True)
            elif self.has_new():
                self._tx(t, self.nxt, False)
                self.nxt += 1
            else:
                break

    def _tx(self, t, seq, retx):
        if self.bulk:
            p = Pkt('T', BULK, seq, MSS, t, None, conn=self)
        else:
            size, gen, cls, dl = self.msgs[seq]
            p = Pkt('T', cls, seq, size + HDR, gen, dl, pid=self.pid, conn=self)
        p.sent = t
        prev = self.sent_t.get(seq)
        self.sent_t[seq] = (t, retx or (prev is not None and prev[1]))
        self.sim.link.enqueue(p)
        if self.rto_at is None:
            self.rto_at = t + self.rto * self.backoff

    def _rtt(self, r):
        if self.srtt is None:
            self.srtt = r; self.rttvar = r / 2.0
        else:
            self.rttvar = 0.75 * self.rttvar + 0.25 * abs(self.srtt - r)
            self.srtt = 0.875 * self.srtt + 0.125 * r
        self.rto = max(200.0, self.srtt + 4.0 * self.rttvar)

    def on_ack(self, t, ackno, sack):
        if ackno > self.una:
            ent = self.sent_t.get(ackno - 1)
            if ent and not ent[1]:
                self._rtt(t - ent[0])
            n = ackno - self.una
            for q in range(self.una, ackno):
                self.sent_t.pop(q, None)
            self.una = ackno
            self.dup = 0; self.backoff = 1
            if not self.rec:
                if self.cwnd < self.ssthresh:
                    self.cwnd += n
                else:
                    self.cwnd += n / self.cwnd
            elif self.una >= self.recover:
                self.rec = False; self.cwnd = self.ssthresh
            self.sacked = {x for x in sack if x >= self.una}
            self.marked = {x for x in self.marked if x >= self.una}
            if self.retx_q:
                self.retx_q = deque(x for x in self.retx_q if x >= self.una and x not in self.sacked)
            self.rto_at = (t + self.rto * self.backoff) if self.una < self.nxt else None
        else:
            self.sacked = {x for x in sack if x >= self.una}
            if self.una < self.nxt:
                self.dup += 1
                if self.dup >= 3 and not self.rec:
                    flight = self.nxt - self.una - len(self.sacked)
                    self.ssthresh = max(flight / 2.0, 2.0)
                    self.cwnd = self.ssthresh
                    self.rec = True; self.recover = self.nxt
                    if self.una not in self.marked:
                        self.marked.add(self.una); self.retx_q.append(self.una)
        if self.rec:
            self._mark_lost()
        self.try_send(t)

    def _mark_lost(self):
        if len(self.sacked) >= 3:
            top = sorted(self.sacked, reverse=True)
            lim = top[2]
            for q in range(self.una, lim):
                if q not in self.sacked and q not in self.marked:
                    self.marked.add(q); self.retx_q.append(q)

    def on_rto(self, t):
        flight = self.nxt - self.una - len(self.sacked)
        self.ssthresh = max(flight / 2.0, 2.0)
        self.cwnd = 1.0; self.rec = False; self.dup = 0
        self.backoff = min(self.backoff * 2, 64)
        self.marked = set(); self.retx_q = deque()
        for q in range(self.una, self.nxt):
            if q not in self.sacked:
                self.marked.add(q); self.retx_q.append(q)
        self.rto_at = t + self.rto * self.backoff
        self.try_send(t)

    # ---------------- receiver ----------------
    def on_data(self, t, seq):
        if seq == self.rcv_nxt:
            if not self.bulk:
                self.deliv[seq] = t
            self.rcv_nxt += 1
            while self.rcv_nxt in self.ooo:
                self.ooo.discard(self.rcv_nxt)
                if not self.bulk:
                    self.deliv[self.rcv_nxt] = t
                self.rcv_nxt += 1
        elif seq > self.rcv_nxt:
            self.ooo.add(seq)
        if not self.sim.ack_lost():
            self.sim.push(t + self.sim.P['prop'], E_TACK, (self, self.rcv_nxt, tuple(self.ooo)))


class Stream:
    """Per (patient, class) state of the proposed transport."""
    __slots__ = ('next', 'pend', 'srtt', 'rttvar')

    def __init__(self):
        self.next = 0; self.pend = {}; self.srtt = 25.0; self.rttvar = 5.0

    def rto(self):
        return max(30.0, self.srtt + 4.0 * self.rttvar)


class Sim:
    def __init__(self, scheme, seed, **over):
        P = dict(DEFAULTS); P.update(over)
        self.P = P; self.scheme = scheme
        self.transport, prio, ddl = SCHEME_CFG[scheme]
        self.rng = random.Random(seed)
        self.h = []; self.cnt = 0
        self.link = Link(P, prio, ddl, self.rng, self)
        self.msglog = []                       # (cls, gen, dl, size, key)
        self.deliv = {}                        # key -> first delivery time (udp/prop)
        self.streams = {}
        self.phat = {}
        self.fec_grp = {}                      # pid -> [gstart, g, count]
        self.rgrp = {}                         # receiver group state
        self.conns = []; self.tconn = {}
        self.stats = defaultdict(int)

    def ack_lost(self):
        if not self.P['ack_loss']:
            return False
        lp = self.P['loss_bad'] if self.link.bad else self.P['loss_good']
        return self.rng.random() < lp

    def push(self, t, kind, data):
        self.cnt += 1
        heapq.heappush(self.h, (t, self.cnt, kind, data))

    # ------------------------------------------------------------------
    def build_schedule(self):
        P = self.P; rng = self.rng; T = P['T']
        gen = defaultdict(list)
        for pid in range(P['N']):
            ph = rng.randrange(PERIOD[ECG])
            for t in range(ph, T, PERIOD[ECG]):
                gen[t].append((pid, ECG))
            ph = rng.randrange(PERIOD[VITAL])
            for t in range(ph, T, PERIOD[VITAL]):
                gen[t].append((pid, VITAL))
            t = rng.expovariate(1.0 / ALARM_MEAN_MS)
            while t < T:
                gen[int(t)].append((pid, ALARM))
                t += rng.expovariate(1.0 / ALARM_MEAN_MS)
        return gen

    def run(self, keep_lat=False):
        P = self.P; T = P['T']
        gen = self.build_schedule()
        if self.transport == 'tcp':
            for pid in range(P['N']):
                c = Conn(self, False, pid)
                self.tconn[pid] = c; self.conns.append(c)
        bulk = []
        for k in range(P['K']):
            c = Conn(self, True, start=self.rng.randrange(500))
            bulk.append(c); self.conns.append(c)
        link = self.link
        h = self.h
        warm = P['warm']; end = T - P['tail']
        for t in range(T):
            if t == warm:
                for c in bulk:
                    c.una_warm = c.una
            if t == end:
                for c in bulk:
                    c.una_end = c.una
            # ---- events
            while h and h[0][0] <= t:
                _, _, kind, data = heapq.heappop(h)
                if kind == E_ARR:
                    self.on_arrival(t, data)
                elif kind == E_TACK:
                    c, ackno, sack = data
                    c.on_ack(t, ackno, sack)
                elif kind == E_PACK:
                    self.on_pack(t, *data)
                elif kind == E_PRTO:
                    self.on_prto(t, *data)
                else:
                    self.on_copy(t, data)
            # ---- application messages
            for pid, cls in gen.get(t, ()):
                self.on_message(t, pid, cls)
            # ---- tcp timers / greedy starts
            for c in self.conns:
                if c.bulk and t == c.start:
                    c.try_send(t)
                if c.rto_at is not None and t >= c.rto_at:
                    c.on_rto(t)
            link.step(t)
        return self.metrics(keep_lat)

    # ------------------------------------------------------------------
    def on_message(self, t, pid, cls):
        size = PAYLOAD[cls]; dl = t + DEADLINE[cls]
        if self.transport == 'tcp':
            c = self.tconn[pid]
            key = (pid, len(c.msgs))
            c.msgs.append((size, t, cls, dl))
            self.msglog.append((cls, t, dl, size, key))
            c.try_send(t)
            return
        st = self.streams.get((pid, cls))
        if st is None:
            st = self.streams[(pid, cls)] = Stream()
        seq = st.next; st.next += 1
        key = (pid, cls, seq)
        self.msglog.append((cls, t, dl, size, key))
        p = Pkt('D', cls, seq, size + HDR, t, dl, pid=pid)
        p.sent = t
        if self.transport == 'prop':
            ph = self.phat.get(pid, 0.0)
            if (self.P['fec_gate'] and self.congested(pid)) or not self.P['use_fec']:
                ph = 0.0
            st.pend[seq] = 0
            self.push(t + st.rto(), E_PRTO, (key, 0))
            if cls == ECG:
                self.fec_tag(t, pid, seq, p, ph)
            elif cls == ALARM and ph > 0.01:
                cp = Pkt('D', cls, seq, size + HDR, t, dl, pid=pid)
                cp.rtt_ok = False
                self.push(t + 10, E_COPY, cp)
        self.link.enqueue(p)
        if self.transport == 'prop' and cls == ECG:
            g = self.fec_grp.get(pid)
            if g and g[2] == g[1] and g[1] > 0:
                par = Pkt('P', ECG, seq, PAYLOAD[ECG] + HDR, t, dl, pid=pid)
                par.gstart = g[0]; par.g = g[1]; par.sent = t
                self.link.enqueue(par)
                self.stats['parity_pkts'] += 1
                self.fec_grp[pid] = None

    def congested(self, pid):
        st = self.streams.get((pid, ECG))
        return st is not None and st.srtt > 1.5 * (2 * self.P['prop'] + 4)

    def fec_tag(self, t, pid, seq, p, ph):
        g = self.fec_grp.get(pid)
        if g is None:
            gs = 0 if ph < 0.01 else (4 if ph < 0.06 else 2)
            g = self.fec_grp[pid] = [seq, gs, 0]
        if g[1] > 0:
            p.gstart = g[0]; p.g = g[1]
        g[2] += 1
        if g[1] == 0:
            self.fec_grp[pid] = None

    def on_copy(self, t, cp):
        st = self.streams[(cp.pid, cp.cls)]
        if cp.seq in st.pend:
            cp.sent = t
            self.link.enqueue(cp)
            self.stats['alarm_copies'] += 1

    def on_arrival(self, t, p):
        if p.kind == 'T':
            p.conn.on_data(t, p.seq)
            return
        key = (p.pid, p.cls, p.seq)
        prop = self.P['prop']
        if p.kind == 'D':
            if key not in self.deliv:
                self.deliv[key] = t
            if self.transport == 'prop':
                if not self.ack_lost():
                    self.push(t + prop, E_PACK, (key, p.sent, p.rtt_ok and p.tries == 0))
                if p.gstart is not None:
                    gk = (p.pid, p.gstart)
                    gr = self.rgrp.get(gk)
                    if gr is None:
                        gr = self.rgrp[gk] = [p.g, set(), False]
                    gr[1].add(p.seq)
                    self.try_recover(t, gk, gr)
        else:  # parity
            gk = (p.pid, p.gstart)
            gr = self.rgrp.get(gk)
            if gr is None:
                gr = self.rgrp[gk] = [p.g, set(), False]
            gr[2] = True
            self.try_recover(t, gk, gr)

    def try_recover(self, t, gk, gr):
        g, got, par = gr
        if par and len(got) == g - 1:
            gs = gk[1]
            for s in range(gs, gs + g):
                if s not in got:
                    key = (gk[0], ECG, s)
                    got.add(s)
                    if key not in self.deliv:
                        self.deliv[key] = t
                        self.stats['fec_recovered'] += 1
                    if not self.ack_lost():
                        self.push(t + self.P['prop'], E_PACK, (key, t, False))
                    break

    def on_pack(self, t, key, sent, rtt_ok):
        pid, cls, seq = key
        st = self.streams[(pid, cls)]
        if seq in st.pend:
            del st.pend[seq]
            if rtt_ok:
                r = t - sent
                st.rttvar = 0.75 * st.rttvar + 0.25 * abs(st.srtt - r)
                st.srtt = 0.875 * st.srtt + 0.125 * r
                self.phat[pid] = 0.98 * self.phat.get(pid, 0.0)

    def on_prto(self, t, key, tries):
        pid, cls, seq = key
        st = self.streams[(pid, cls)]
        if st.pend.get(seq) != tries:
            return
        self.phat[pid] = 0.98 * self.phat.get(pid, 0.0) + 0.02
        gen_t = None
        # find deadline of this message from the log index (stored in pend via key math)
        dl = self.dl_of(pid, cls, seq)
        if tries < 3 and t + 0.5 * st.srtt <= dl:
            p = Pkt('D', cls, seq, PAYLOAD[cls] + HDR, 0, dl, pid=pid)
            p.sent = t; p.tries = tries + 1; p.rtt_ok = False
            self.link.enqueue(p)
            self.stats['retx_pkts'] += 1
            st.pend[seq] = tries + 1
            self.push(t + st.rto() * (1.5 ** (tries + 1)), E_PRTO, (key, tries + 1))
        else:
            del st.pend[seq]

    def dl_of(self, pid, cls, seq):
        return self.dl_cache[(pid, cls, seq)]

    # ------------------------------------------------------------------
    def metrics(self, keep_lat):
        P = self.P; warm = P['warm']; end = P['T'] - P['tail']
        lat = defaultdict(list); tot = defaultdict(int); ok = defaultdict(int)
        deliv_n = defaultdict(int)
        base_bytes = 0
        for cls, gen, dl, size, key in self.msglog:
            base_bytes += size + HDR
            if gen < warm or gen >= end:
                continue
            if self.transport == 'tcp':
                d = self.tconn[key[0]].deliv.get(key[1])
            else:
                d = self.deliv.get(key)
            tot[cls] += 1
            if d is not None:
                deliv_n[cls] += 1
                lat[cls].append(d - gen)
                if d <= dl:
                    ok[cls] += 1
        m = {}
        allt = sum(tot.values()); allok = sum(ok.values())
        for cls in (ALARM, ECG, VITAL):
            n = tot[cls]
            L = sorted(lat[cls])
            m['tdr_' + CLS_NAME[cls]] = ok[cls] / n if n else float('nan')
            m['dr_' + CLS_NAME[cls]] = deliv_n[cls] / n if n else float('nan')
            m['mean_' + CLS_NAME[cls]] = (sum(L) / len(L)) if L else float('nan')
            m['p99_' + CLS_NAME[cls]] = L[min(len(L) - 1, int(0.99 * len(L)))] if L else float('nan')
        m['tdr_all'] = allok / allt if allt else float('nan')
        win = end - warm
        m['bulk_mbps'] = sum(c.una_end - c.una_warm for c in self.conns if c.bulk) * MSS * 8.0 / (win * 1000.0)
        m['overhead'] = self.link.offered_tel / base_bytes if base_bytes else float('nan')
        m['drops_queue'] = sum(self.link.drops_q[c] for c in (ALARM, ECG, VITAL))
        m['drops_deadline'] = sum(self.link.drops_d[c] for c in (ALARM, ECG, VITAL))
        m['drops_loss'] = sum(self.link.drops_l[c] for c in (ALARM, ECG, VITAL))
        for k in ('retx_pkts', 'parity_pkts', 'fec_recovered', 'alarm_copies'):
            m[k] = self.stats[k]
        if keep_lat:
            m['_lat'] = {CLS_NAME[c]: lat[c] for c in (ALARM, ECG, VITAL)}
            m['_tot'] = {CLS_NAME[c]: tot[c] for c in (ALARM, ECG, VITAL)}
        return m


def _prep(sim):
    # deadline lookup for ARQ (message deadline is fixed by class)
    class DL(dict):
        def __missing__(self, k):
            pid, cls, seq = k
            return self.owner.dl_table[(pid, cls)][seq]
    sim.dl_cache = DL(); sim.dl_cache.owner = sim
    sim.dl_table = defaultdict(list)


def run_one(scheme, seed, keep_lat=False, **over):
    sim = Sim(scheme, seed, **over)
    _prep(sim)
    # register deadlines as messages are created
    orig = sim.on_message

    def wrapped(t, pid, cls):
        if sim.transport != 'tcp':
            st = sim.streams.get((pid, cls))
            seq = st.next if st else 0
            sim.dl_table[(pid, cls)].append(t + DEADLINE[cls])
            assert len(sim.dl_table[(pid, cls)]) == seq + 1
        orig(t, pid, cls)
    sim.on_message = wrapped
    return sim.run(keep_lat)


if __name__ == '__main__':
    scheme = sys.argv[1] if len(sys.argv) > 1 else 'Proposed'
    t0 = time.time()
    r = run_one(scheme, 1)
    print(scheme, 'runtime %.1fs' % (time.time() - t0))
    for k, v in r.items():
        print('  %-16s %s' % (k, ('%.4f' % v) if isinstance(v, float) else v))
