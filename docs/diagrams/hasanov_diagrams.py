"""Habib Hasanov's diagrams for report sections 4 (anti-entropy) and 5 (consensus).

    python docs/diagrams/hasanov_diagrams.py      (needs matplotlib; writes PNGs next to this file)

paxos_lwt.png            Paxos v1 round of INSERT ... IF NOT EXISTS (prepare/promise, read,
                         propose/accept, commit) and the losing proposer's path
antientropy_merkle.png   the three repair mechanisms side by side, with a Merkle-tree
                         comparison that narrows a mismatch down to one token sub-range

Reuses Person 2's sequence-diagram helper (p2_diagrams.Seq) so all diagrams share one style.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from p2_diagrams import (BLUE_FILL, GRAY, GREEN, INK, NAVY, ORANGE, OUT, Seq,  # noqa: E402
                         FancyBboxPatch, plt)

RED = "#B23B3B"


def paxos_lwt():
    s = Seq("Lightweight transaction = one Paxos instance per partition (v1: 4 round trips, ballots, no leader)",
            [("c", "Client\nINSERT … IF NOT EXISTS"), ("co", "cass1\ncoordinator = proposer"),
             ("r2", "cass2\nacceptor"), ("r3", "cass3\nacceptor")], height=9.7, width=10.4)
    s.band(1.35, 3.65, "phase 1  prepare / promise")
    s.msg("c", "co", 1.7, "'alice' IF NOT EXISTS (SERIAL / QUORUM)")
    s.note("co", 2.1, "ballot b = new timeuuid (> any ballot seen)", fc="#FFF8E7", ec=ORANGE)
    s.msg("co", "r2", 2.6, "PREPARE(b)", color=ORANGE)
    s.msg("co", "r3", 2.9, "PREPARE(b)", color=ORANGE)
    s.msg("r2", "co", 3.3, "PROMISE(b) + last accepted (b', v') if any", color=GREEN, dashed=True)
    s.note("co", 3.62, "needs a majority (2 of 3; the coordinator is also an acceptor)", fc="#FFFFFF", ec=GRAY)
    s.band(3.85, 5.25, "phase 2  read & check")
    s.note("co", 4.15, "if a promise returned an unfinished proposal → re-propose it first (repair)",
           fc="#FFFFFF", ec=GRAY)
    s.msg("co", "r2", 4.6, "READ current row (QUORUM)", color=NAVY)
    s.msg("r2", "co", 4.95, "row absent", color=GREEN, dashed=True)
    s.band(5.45, 7.05, "phase 3  propose / accept")
    s.note("co", 5.75, "condition IF NOT EXISTS holds → value v = (alice, client-03)", fc="#EEF5EA", ec=GREEN)
    s.msg("co", "r2", 6.25, "PROPOSE(b, v)", color=ORANGE)
    s.msg("co", "r3", 6.55, "PROPOSE(b, v)", color=ORANGE)
    s.msg("r3", "co", 6.95, "ACCEPT(b)  - only if no higher ballot promised", color=GREEN, dashed=True)
    s.band(7.25, 8.75, "phase 4  commit")
    s.msg("co", "r2", 7.75, "COMMIT(b, v): normal write", color=NAVY)
    s.msg("co", "r3", 8.05, "COMMIT(b, v), CL QUORUM", color=NAVY)
    s.msg("co", "c", 8.5, "[applied] = True", color=GREEN)
    s.note("c", 9.25, "Concurrent proposer with ballot b2 > b:\nacceptors reject b → retry; "
                     "if its read sees the row:\n[applied] = False + current owner (no propose)",
           fc="#FDECEA", ec=RED, dx=1.3)
    s.note("r3", 9.3, "Split-brain prevention: any two majorities\nof 3 replicas intersect, so two sides of a\n"
                       "partition can never both complete a round", fc="#FFFFFF", ec=NAVY, dx=-0.9)
    s.save("paxos_lwt.png")


def antientropy_merkle():
    fig, axes = plt.subplots(1, 3, figsize=(10.4, 4.1), gridspec_kw={"width_ratios": [1, 1, 1.35]})
    titles = ["(a) Hinted handoff", "(b) Read repair", "(c) Anti-entropy repair (Merkle trees)"]
    for ax, t in zip(axes, titles):
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 10)
        ax.axis("off")
        ax.text(0.1, 9.9, t, fontsize=10, weight="bold", color=INK, va="top")

    def node(ax, x, y, label, fc=BLUE_FILL, ec=NAVY, w=3.2, h=1.3):
        ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle="round,pad=0.05", fc=fc, ec=ec, lw=1.1))
        ax.text(x, y, label, ha="center", va="center", fontsize=8, color=INK)

    def arrow(ax, a, b, label="", color=NAVY, dashed=False, dy=0.25):
        ax.annotate("", xy=b, xytext=a, arrowprops=dict(arrowstyle="-|>", color=color, lw=1.3,
                                                        ls="--" if dashed else "-"))
        if label:
            ax.text((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + dy, label, ha="center", fontsize=7.4, color=color)

    a = axes[0]
    node(a, 2.2, 6.8, "cass1\ncoordinator")
    node(a, 7.8, 6.8, "cass3\nDOWN", fc="#F3F4F6", ec=GRAY)
    a.add_patch(FancyBboxPatch((0.6, 3.7), 3.2, 1.3, boxstyle="round,pad=0.05", fc="#FFF8E7", ec=ORANGE))
    a.text(2.2, 4.35, "hints/*.hints\n(local file)", ha="center", va="center", fontsize=7.6)
    arrow(a, (2.2, 6.2), (2.2, 5.05), "store", ORANGE, dy=0.0)
    arrow(a, (3.8, 4.35), (7.8, 6.1), "", GREEN, dashed=True)
    a.text(7.6, 3.6, "replay when gossip\nsees cass3 UP", fontsize=7.4, color=GREEN, ha="center")
    a.text(0.2, 2.4, "• written for a replica that is down or times out\n• only within max_hint_window (3 h)\n"
                     "• never counts toward the CL (except ANY)\n• best effort: lost if the coordinator dies",
           fontsize=7.4, color=INK, va="top")

    b = axes[1]
    node(b, 2.0, 7.2, "coordinator", w=3.0)
    node(b, 8.1, 8.3, "cass1 (t2)", fc="#EEF5EA", ec=GREEN, w=2.8)
    node(b, 8.1, 5.6, "cass3 (t1)", fc="#FDECEA", ec=RED, w=2.8)
    arrow(b, (3.5, 7.5), (6.7, 8.2), "data", NAVY, dy=0.2)
    arrow(b, (3.5, 6.9), (6.7, 5.9), "", RED)
    b.text(5.6, 6.95, "digest ≠", fontsize=7.4, color=RED, ha="left")
    arrow(b, (6.7, 5.3), (2.6, 6.5), "", ORANGE, dashed=True)
    b.text(3.6, 5.2, "write back t2", fontsize=7.4, color=ORANGE, ha="center")
    b.text(0.2, 3.6, "• during a read at CL > ONE\n• repairs only the rows read, on the\n  replicas contacted\n"
                     "• BLOCKING (4.0+): client waits for it\n• never-read rows stay stale (Exp 4b)",
           fontsize=7.4, color=INK, va="top")

    c = axes[2]
    def tree(x0, label, bad):
        lv = [(x0 + 2.0, 8.2)]
        mid = [(x0 + 0.9, 6.7), (x0 + 3.1, 6.7)]
        leaves = [(x0 + 0.35, 5.2), (x0 + 1.45, 5.2), (x0 + 2.55, 5.2), (x0 + 3.65, 5.2)]
        for (px, py), kids in ((lv[0], mid), (mid[0], leaves[:2]), (mid[1], leaves[2:])):
            for kx, ky in kids:
                c.plot([px, kx], [py - 0.3, ky + 0.3], color=GRAY, lw=0.9)
        for i, (x, y) in enumerate(lv + mid + leaves):
            hot = bad and i in (0, 2, 5)
            c.add_patch(FancyBboxPatch((x - 0.42, y - 0.3), 0.84, 0.6, boxstyle="round,pad=0.03",
                                       fc="#FDECEA" if hot else BLUE_FILL, ec=RED if hot else NAVY, lw=1))
            c.text(x, y, "h" if i < 3 else f"r{i - 2}", ha="center", va="center", fontsize=7)
        c.text(x0 + 2.0, 8.75, label, ha="center", fontsize=8, color=INK)
    tree(0.2, "cass1 tree (validation)", False)
    tree(5.4, "cass3 tree", True)
    c.annotate("", xy=(7.4, 8.2), xytext=(2.6, 8.2), arrowprops=dict(arrowstyle="<->", color=RED, lw=1.1))
    c.text(5.0, 7.75, "roots differ", ha="center", fontsize=7.4, color=RED)
    c.text(0.2, 4.1, "• hash tree per token range, built by a validation compaction on every replica\n"
                     "• compare top-down: equal subtree → skip; descend only into differences\n"
                     "• stream only mismatching ranges (here r3) → covers never-read rows\n"
                     "• full / incremental / --preview (estimate only, Exp 4) / subrange\n"
                     "• must complete within gc_grace_seconds, or deleted data can return",
           fontsize=7.4, color=INK, va="top")
    fig.tight_layout()
    path = os.path.join(OUT, "antientropy_merkle.png")
    fig.savefig(path, dpi=200)
    plt.close(fig)
    print("wrote", path)


if __name__ == "__main__":
    paxos_lwt()
    antientropy_merkle()
