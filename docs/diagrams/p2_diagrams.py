"""Person 2 diagrams for report section 3 (consistency model, read/write paths).

    python docs/diagrams/p2_diagrams.py        (needs matplotlib; writes PNGs next to this file)

write_path.png      coordinator-based write at QUORUM, commit log + memtable, hints
read_path.png       data + digest read at QUORUM, mismatch, blocking read repair
quorum_overlap.png  replica sets touched by W and R for the five CL pairs of Exp 2
"""
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

OUT = os.path.dirname(os.path.abspath(__file__))
NAVY, BLUE_FILL, ORANGE, GREEN, GRAY, INK = "#2E5597", "#DCE6F2", "#C55A11", "#4E7D32", "#7F7F7F", "#1A1A1A"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9})


class Seq:
    """Tiny sequence-diagram helper: lifelines at fixed x, events at increasing y."""

    def __init__(self, title, actors, height, width=10.0):
        self.fig, self.ax = plt.subplots(figsize=(width, height))
        self.ax.set_xlim(0, width)
        self.ax.set_ylim(height, 0)
        self.ax.axis("off")
        self.x = {}
        n = len(actors)
        for i, (key, label) in enumerate(actors):
            x = 1.0 + i * (width - 2.0) / (n - 1)
            self.x[key] = x
            self.ax.add_patch(FancyBboxPatch((x - 0.78, 0.55), 1.56, 0.62, boxstyle="round,pad=0.02",
                                             fc=BLUE_FILL, ec=NAVY, lw=1.2))
            self.ax.text(x, 0.86, label, ha="center", va="center", fontsize=8.5, color=INK)
            self.ax.plot([x, x], [1.17, height - 0.2], color=GRAY, lw=0.8, ls=(0, (4, 3)), zorder=0)
        self.ax.text(0.1, 0.25, title, fontsize=11, color=INK, weight="bold", va="center")

    def msg(self, a, b, y, label, color=NAVY, dashed=False, above=True, fs=7.8):
        xa, xb = self.x[a], self.x[b]
        self.ax.annotate("", xy=(xb, y), xytext=(xa, y),
                         arrowprops=dict(arrowstyle="-|>", color=color, lw=1.3,
                                         ls="--" if dashed else "-", shrinkA=2, shrinkB=2))
        self.ax.text((xa + xb) / 2, y - 0.08 if above else y + 0.2, label, ha="center", va="bottom",
                     fontsize=fs, color=color)

    def note(self, key, y, text, color=INK, fc="#FFFFFF", ec=GRAY, dx=0.0, ha="center", w=None):
        x = self.x[key] + dx
        self.ax.text(x, y, text, ha=ha, va="center", fontsize=7.4, color=color,
                     bbox=dict(boxstyle="round,pad=0.3", fc=fc, ec=ec, lw=0.8))

    def band(self, y0, y1, text):
        self.ax.axhspan(y0, y1, color="#F3F4F6", zorder=-1)
        self.ax.text(9.95 * self.ax.get_xlim()[1] / 10, y0 + 0.12, text, ha="right", va="top",
                     fontsize=7.5, color=GRAY, style="italic")

    def save(self, name):
        self.fig.tight_layout()
        path = os.path.join(OUT, name)
        self.fig.savefig(path, dpi=200)
        plt.close(self.fig)
        print("wrote", path)


def write_path():
    s = Seq("Write path at CL = QUORUM (N = RF = 3, W = 2)",
            [("c", "Client\n(token-aware driver)"), ("co", "cass1\ncoordinator + replica"),
             ("r2", "cass2\nreplica"), ("r3", "cass3\nreplica")], height=7.4)
    s.msg("c", "co", 1.7, "INSERT … (CL QUORUM), client timestamp t")
    s.note("co", 2.15, "replicas = tokens(hash(room)) → {cass1, cass2, cass3}\n"
                       "alive replicas ≥ W ?  else → Unavailable (nothing written)", fc="#FFF8E7", ec=ORANGE)
    s.msg("co", "r2", 2.85, "MUTATION_REQ", color=ORANGE)
    s.msg("co", "r3", 3.2, "MUTATION_REQ", color=ORANGE)
    for key, y in (("co", 3.8), ("r2", 3.8), ("r3", 3.8)):
        s.note(key, y, "1. append commit log\n2. apply to memtable", fc="#EEF5EA", ec=GREEN)
    s.msg("r2", "co", 4.55, "MUTATION_RSP (ack)", color=GREEN, dashed=True)
    s.note("co", 4.95, "local ack + cass2 ack = 2 = W", fc="#EEF5EA", ec=GREEN)
    s.msg("co", "c", 5.45, "success (≈ max of the 2 fastest acks)", color=GREEN)
    s.msg("r3", "co", 5.85, "late ack - still applied, just not waited for", color=GRAY, dashed=True)
    s.band(6.2, 7.3, "background")
    s.note("co", 6.55, "if a replica is down: coordinator stores a HINT\n(replayed on return; does not count toward W)",
           fc="#FFFFFF", ec=GRAY)
    s.note("r3", 6.75, "memtable full → flush to\nimmutable SSTable; compaction", fc="#FFFFFF", ec=GRAY)
    s.note("c", 6.95, "write timeout ≠ rollback:\nthe write may still be applied", fc="#FFFFFF", ec=ORANGE)
    s.save("write_path.png")


def read_path():
    s = Seq("Read path at CL = QUORUM (R = 2) with digest mismatch and blocking read repair",
            [("c", "Client"), ("co", "cass2\ncoordinator"), ("r1", "cass1\nreplica (fresh)"),
             ("r3", "cass3\nreplica (stale)")], height=8.85)
    s.msg("c", "co", 1.7, "SELECT … WHERE room = ? (CL QUORUM)")
    s.note("co", 2.15, "pick R = 2 replicas, closest first (dynamic snitch)", fc="#FFF8E7", ec=ORANGE)
    s.msg("co", "r1", 2.75, "READ_REQ  (full data)", color=NAVY)
    s.msg("co", "r3", 3.1, "READ_REQ  (digest only = hash)", color=NAVY)
    s.msg("r1", "co", 3.65, "data, newest cell ts = t2", color=GREEN, dashed=True)
    s.msg("r3", "co", 4.0, "digest(ts = t1)", color=GREEN, dashed=True)
    s.note("co", 4.45, "digest ≠ hash(data)  →  DIGEST MISMATCH", fc="#FDECEA", ec="#B23B3B")
    s.msg("co", "r1", 4.95, "READ_REQ  (full data)", color=NAVY)
    s.msg("co", "r3", 5.3, "READ_REQ  (full data)  - every replica of the first round", color=NAVY)
    s.msg("r1", "co", 5.75, "data, t2", color=GREEN, dashed=True)
    s.msg("r3", "co", 6.1, "data, ts = t1", color=GREEN, dashed=True)
    s.note("co", 6.55, "reconcile per cell: highest timestamp wins (LWW) → t2", fc="#EEF5EA", ec=GREEN)
    s.msg("co", "r3", 7.05, "read-repair MUTATION (t2)", color=ORANGE)
    s.msg("r3", "co", 7.4, "ack", color=GREEN, dashed=True)
    s.msg("co", "c", 7.85, "result (t2)  -  returned only after repair (BLOCKING, default since 4.0)", color=GREEN)
    s.note("c", 8.4, "CL ONE: 1 replica, no digest, no read repair\n"
                      "slow replica: speculative retry after the table's p99 (99p)", fc="#FFFFFF", ec=GRAY, dx=1.2)
    s.save("read_path.png")


def quorum_overlap():
    pairs = [("ONE", "ONE", 1, 1), ("ONE", "QUORUM", 1, 2), ("QUORUM", "QUORUM", 2, 2),
             ("ALL", "ONE", 3, 1), ("ONE", "ALL", 1, 3)]
    fig, axes = plt.subplots(1, len(pairs), figsize=(10, 2.9))
    for ax, (wn, rn, w, r) in zip(axes, pairs):
        ax.set_xlim(0, 3)
        ax.set_ylim(0, 3.3)
        ax.axis("off")
        # worst case: the read picks replicas starting from the far end of the write set
        wset = set(range(w))
        rset = set(range(3 - r, 3))
        for i in range(3):
            x = 0.5 + i
            ax.add_patch(FancyBboxPatch((x - 0.38, 1.25), 0.76, 0.76, boxstyle="round,pad=0.02",
                                        fc=BLUE_FILL, ec=NAVY, lw=1))
            ax.text(x, 1.63, f"cass{i + 1}", ha="center", va="center", fontsize=7.5)
            if i in wset:
                ax.add_patch(plt.Rectangle((x - 0.38, 2.12), 0.76, 0.22, fc=ORANGE, ec="none"))
                ax.text(x, 2.23, "W", ha="center", va="center", color="white", fontsize=7, weight="bold")
            if i in rset:
                ax.add_patch(plt.Rectangle((x - 0.38, 0.92), 0.76, 0.22, fc=GREEN, ec="none"))
                ax.text(x, 1.03, "R", ha="center", va="center", color="white", fontsize=7, weight="bold")
        ok = w + r > 3
        ax.text(1.5, 2.95, f"W={wn} ({w}), R={rn} ({r})", ha="center", fontsize=8.2, color=INK)
        ax.text(1.5, 0.55, f"R+W = {w + r} {'>' if ok else '≤'} N = 3", ha="center", fontsize=8.2,
                color=GREEN if ok else "#B23B3B", weight="bold")
        ax.text(1.5, 0.2, "overlap guaranteed" if ok else "may miss the write → stale",
                ha="center", fontsize=7.5, color=GREEN if ok else "#B23B3B")
    fig.suptitle("Quorum intersection (worst-case choice of replicas): a read sees the latest acknowledged "
                 "write only if R + W > N", fontsize=9.5, x=0.01, ha="left")
    fig.tight_layout()
    path = os.path.join(OUT, "quorum_overlap.png")
    fig.savefig(path, dpi=200)
    plt.close(fig)
    print("wrote", path)


if __name__ == "__main__":
    write_path()
    read_path()
    quorum_overlap()
