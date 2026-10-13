#!/usr/bin/env python3
"""Validation model: a slot-level IEEE 802.11g DCF replica of the ns-3 scenario in
healthcare-telemetry-ns3 (healthcare-wireless.cc).

Scenario (copied from the repo source): healthcare station (80 kbit/s, 100 B packets, UDP or TCP) and a
background station (CBR UDP, 1000 B packets, 1/4/8 Mbit/s) both send to one AP at a constant 6 Mbit/s
(ErpOfdmRate6Mbps) rate, applications run 2 s..9 s, simulation ends at 15 s.

Modelled: DCF carrier sensing with binary exponential backoff, collisions, MAC ACKs, a 500-packet / 500 ms
per-station queue, and (for TCP) delayed ACKs sent back by the AP through the same channel.
Not modelled: TCP congestion dynamics (the flow is application-limited at 80 kbit/s), PHY errors (the ns-3
nodes all sit at the same position, so the channel is lossless), rate adaptation.
Metrics follow ns-3 FlowMonitor: delay = mean IP-packet delay, jitter = mean |delay_i - delay_{i-1}|,
throughput = rxBytes*8/(last rx - first rx) counting IP bytes.
"""
import math, random, heapq

SLOT, SIFS = 9e-6, 10e-6
DIFS = SIFS + 2 * SLOT
CWMIN, CWMAX, RETRY = 15, 1023, 7
RATE = 6e6
PLCP, SIGEXT = 20e-6, 6e-6
MAC_OVH = 24 + 8 + 4            # MAC header + LLC/SNAP + FCS
QMAX, QDELAY = 500, 0.5


def frame_time(ip_bytes):
    bits = 16 + 8 * (ip_bytes + MAC_OVH) + 6
    return PLCP + math.ceil(bits / 24) * 4e-6 + SIGEXT


ACK_T = PLCP + math.ceil((16 + 8 * 14 + 6) / 24) * 4e-6 + SIGEXT
ACK_TIMEOUT = SIFS + ACK_T + SLOT


class Station:
    def __init__(self, name):
        self.name = name
        self.q = []          # packets: dict(t, size, flow, id)
        self.cw = CWMIN
        self.b = 0           # remaining backoff slots
        self.retry = 0
        self.fresh = True

    def head(self):
        return self.q[0] if self.q else None


def run_wifi(protocol, bg_mbps, seed=1, start=2.0, stop=9.0, end=15.0, jitter_start=0.0):
    rnd = random.Random(seed)
    hc_ip = 100 + (28 if protocol == 'udp' else 52)      # IP bytes per healthcare packet
    bg_ip = 1000 + 28
    hc, bg, ap = Station('hc'), Station('bg'), Station('ap')
    sts = [hc, bg, ap]
    # packet arrival schedule
    arr = []
    t0 = start + rnd.uniform(0, jitter_start)
    n = int(round((stop - start) * 100))
    for i in range(n):
        arr.append((t0 + i * 0.01, 'hc', hc_ip, i))
    t1 = start + rnd.uniform(0, jitter_start)
    gap = 1000 * 8 / (bg_mbps * 1e6)
    for i in range(int((stop - start) / gap) + 1):
        tt = t1 + i * gap
        if tt < stop:
            arr.append((tt, 'bg', bg_ip, i))
    arr.sort(key=lambda a: a[0])
    ai = 0
    stats = {'hc': dict(tx=0, rx=0, bytes=0, delays=[], first=None, last=None),
             'bg': dict(tx=0, rx=0, bytes=0, delays=[], first=None, last=None)}
    t = 0.0
    idle_start = 0.0
    tcp_pending = 0

    def enqueue_until(tm):
        nonlocal ai
        while ai < len(arr) and arr[ai][0] <= tm:
            at, fl, sz, pid = arr[ai]
            ai += 1
            st = hc if fl == 'hc' else bg
            stats[fl]['tx'] += 1
            if len(st.q) >= QMAX:
                continue
            was_empty = not st.q
            st.q.append(dict(t=at, size=sz, flow=fl, id=pid))
            if was_empty:
                # medium state at arrival: backoff only if medium busy (arrival before idle_start+DIFS)
                st.b = 0 if at >= idle_start + DIFS else rnd.randint(0, st.cw)

    while True:
        enqueue_until(t)
        # drop expired head packets
        for st in sts:
            while st.q and (t - st.q[0]['t']) > QDELAY:
                st.q.pop(0)
                st.cw, st.retry = CWMIN, 0
                st.b = rnd.randint(0, st.cw)
        backlogged = [s for s in sts if s.q]
        if not backlogged:
            if ai >= len(arr):
                break
            t = max(t, arr[ai][0])
            if t > end:
                break
            continue
        base = max(idle_start + DIFS, t)
        fire = {s: max(base, s.q[0]['t']) + s.b * SLOT for s in backlogged}
        tmin = min(fire.values())
        # a new arrival before tmin may preempt (arrives idle -> immediate tx)
        if ai < len(arr) and arr[ai][0] < tmin:
            t = arr[ai][0]
            enqueue_until(t)
            continue
        if tmin > end:
            break
        winners = [s for s in backlogged if abs(fire[s] - tmin) < 1e-12]
        # decrement others' counters by elapsed idle slots
        for s in backlogged:
            if s not in winners:
                el = tmin - max(base, s.q[0]['t'])
                s.b = max(0, s.b - int(el / SLOT + 1e-9))
        ftimes = [frame_time(s.q[0]['size']) for s in winners]
        if len(winners) == 1:
            s = winners[0]
            pk = s.q[0]
            ft = ftimes[0]
            rx_t = tmin + ft
            idle_start = rx_t + SIFS + ACK_T
            t = idle_start
            s.q.pop(0)
            s.cw, s.retry = CWMIN, 0
            s.b = rnd.randint(0, s.cw)
            if pk['flow'] in ('hc', 'bg'):
                f = stats[pk['flow']]
                f['rx'] += 1
                f['bytes'] += pk['size']
                d = rx_t - pk['t']
                f['delays'].append(d)
                if f['first'] is None:
                    f['first'] = rx_t
                f['last'] = rx_t
                if protocol == 'tcp' and pk['flow'] == 'hc':
                    tcp_pending += 1
                    if tcp_pending >= 2:           # delayed ACK every 2nd segment
                        tcp_pending = 0
                        ap.q.append(dict(t=rx_t, size=52, flow='ack', id=0))
                        if len(ap.q) == 1:
                            ap.b = rnd.randint(0, ap.cw)
        else:
            tend = tmin + max(ftimes) + ACK_TIMEOUT
            idle_start = tend
            t = tend
            for s in winners:
                s.retry += 1
                if s.retry > RETRY:
                    s.q.pop(0)
                    s.cw, s.retry = CWMIN, 0
                else:
                    s.cw = min(2 * s.cw + 1, CWMAX)
                s.b = rnd.randint(0, s.cw)
        if t > end:
            break

    out = {}
    for k in ('hc', 'bg'):
        f = stats[k]
        d = f['delays']
        thr = 0.0
        if f['rx'] > 1 and f['last'] > f['first']:
            thr = f['bytes'] * 8 / (f['last'] - f['first']) / 1000
        jit = (sum(abs(d[i] - d[i - 1]) for i in range(1, len(d))) / (len(d) - 1)) if len(d) > 1 else 0
        out[k] = dict(tx=f['tx'], rx=f['rx'], lost=f['tx'] - f['rx'], thr_kbps=thr,
                      delay_ms=1000 * sum(d) / len(d) if d else 0, jitter_ms=1000 * jit)
    return out


if __name__ == '__main__':
    for p in ('udp', 'tcp'):
        for l in (1, 4, 8):
            r = run_wifi(p, l, 1)
            print(p, l, {k: {a: round(b, 3) for a, b in v.items()} for k, v in r.items()})
