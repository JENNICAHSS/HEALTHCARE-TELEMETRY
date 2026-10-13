import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

plt.rcParams['font.family'] = 'serif'
plt.rcParams['font.serif'] = ['Times New Roman', 'Liberation Serif', 'DejaVu Serif']
fig, ax = plt.subplots(figsize=(7.16, 2.55))
ax.set_xlim(0, 100); ax.set_ylim(0, 39); ax.axis('off')

def box(x, y, w, h, title, lines, fc):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0.2,rounding_size=0.8',
                                fc=fc, ec='#333333', lw=0.8))
    ax.text(x + w / 2, y + h - 2.2, title, ha='center', va='top', fontsize=6.6, fontweight='bold')
    ax.text(x + w / 2, y + h - 7.6, '\n'.join(lines), ha='center', va='top', fontsize=5.7, linespacing=1.25)

def arrow(x1, y1, x2, y2, style='-|>', ls='-', rad=0.0):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style, mutation_scale=7,
                                 lw=0.8, color='#222222', linestyle=ls,
                                 connectionstyle='arc3,rad=%s' % rad))

H = 21; Y = 10
box(0.5,  Y, 12.5, H, 'Telemetry\nSources', ['Alarm events', 'ECG stream', 'Vital signs', '(per patient)'], '#E8E8F5')
box(15.5, Y, 13.5, H, 'Traffic Class\nMarker', ['Class 0/1/2 tag', 'Deadline stamp', 'Per-stream', 'sequence no.'], '#F4EBD0')
box(31.5, Y, 16.5, H, 'Reliability\nEngine', ['Deadline-aware ARQ', 'Adaptive FEC (ECG)', 'Alarm redundancy', 'Congestion gate'], '#D9EAD3')
box(50.5, Y, 15.5, H, 'Priority Queue\n(Access Point)', ['Strict priority', 'Deadline-aware drop', 'Class 3: bulk', 'traffic'], '#FCE4D6')
box(68.5, Y, 13.0, H, 'Wireless\nChannel', ['Bursty loss', '(Gilbert-Elliott)', 'Shared capacity', 'Backhaul delay'], '#E2EFDA')
box(84.0, Y, 15.5, H, 'Receiver &\nMonitoring', ['Out-of-order', 'delivery', 'FEC decode, ACK', 'Clinical display'], '#DDEBF7')

for x1, x2 in [(13.2, 15.3), (29.2, 31.3), (48.2, 50.3), (66.2, 68.3), (81.7, 83.8)]:
    arrow(x1, Y + H / 2, x2, Y + H / 2)

# feedback path
ax.add_patch(FancyBboxPatch((33.5, 0.8), 30, 5.2, boxstyle='round,pad=0.2,rounding_size=0.8',
                            fc='#FFF2CC', ec='#333333', lw=0.8))
ax.text(48.5, 3.4, 'Feedback: ACK / RTT / loss estimate (p̂)', ha='center', va='center', fontsize=6.0)
arrow(91.7, Y - 0.2, 91.7, 3.4, style='-')
arrow(91.7, 3.4, 63.8, 3.4)
arrow(40.0, 6.1, 40.0, Y - 0.2)
ax.text(70, 5.0, 'return path (lossless, 10 ms)', fontsize=5.3, style='italic', ha='left')

# cross traffic
ax.text(58.2, 37.2, 'Background bulk TCP flows (cross traffic)', ha='center', fontsize=5.8)
arrow(58.2, 35.8, 58.2, Y + H + 0.6, ls='--')
fig.savefig('figs/fig_arch.pdf', bbox_inches='tight', pad_inches=0.03)
fig.savefig('figs/fig_arch.png', dpi=200, bbox_inches='tight', pad_inches=0.03)
