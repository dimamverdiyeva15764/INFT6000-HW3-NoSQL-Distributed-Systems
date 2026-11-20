"""Figure E - Paxos v1 lightweight transaction, winner and loser, as seen in our Exp 6 query traces."""
import sys
from svgkit import SVG, C, INK, INK2, MUTED

s = SVG(1600, 900, "Paxos v1 lightweight transaction - Group 4")
s.text(800, 34, "Lightweight transaction (INSERT ... IF NOT EXISTS) = one Paxos v1 instance per partition",
       size=20, weight="bold", anchor="middle")
s.text(800, 56, "Message names copied from our Exp 6 traces (paxos_variant = v1, coordinator cass1). "
       "No leader: any coordinator can propose; ballots, not a stable leader, order competing proposals.",
       size=13.5, color=INK2, anchor="middle", italic=True)
PAX = "#8e44ad"


def panel(x0, title, sub, life_end):
    s.boundary(x0, 92, 770, 790, title, "#fbfbfa", "#3d3d39", sw=1.5, size=14)
    s.text(x0 + 16, 122, sub, size=12, color=INK2, italic=True)
    xs = {}
    for i, (key, label, sub2, col) in enumerate([("drv", "Client", "serial CL SERIAL", C["cql"]),
                                                  ("c1", "cass1", "coordinator = proposer", C["gossip"]),
                                                  ("c2", "cass2", "acceptor", C["gossip"]),
                                                  ("c3", "cass3", "acceptor", C["gossip"])]):
        cx = x0 + 90 + i * 196
        xs[key] = cx
        s.rect(cx - 78, 138, 156, 50, fill="#ffffff", stroke=col, sw=1.8, rx=7)
        s.text(cx, 158, label, size=13, weight="bold", anchor="middle")
        s.text(cx, 176, sub2, size=11, color=INK2, anchor="middle")
        s.add(f'<path d="M{cx},188 L{cx},{life_end}" stroke="#bdbdb6" stroke-width="1.4" stroke-dasharray="4 4"/>')
    return xs


def msg(xs, a, b, y, label, kind="repl", col=None):
    x1, x2 = xs[a], xs[b]
    off = 6 if x2 > x1 else -6
    s.edge([(x1 + off, y), (x2 - off, y)], kind, label=label, lx=(x1 + x2) / 2, ly=y - 7, lsize=11.3, lcolor=col)


def phase(x0, y, h, label):
    s.rect(x0 + 10, y, 750, h, fill="#f4eefa", stroke="none", rx=6, opacity=0.8)
    s.text(x0 + 754, y + 16, label, size=11.5, color=PAX, anchor="end", italic=True, weight="bold")


def act(x, y, w, title, fill="#fff6f0", stroke="#f0b08f"):
    s.box(x - w / 2, y, w, 30, title, [], fill=fill, stroke=stroke, size=11.3)


for x0, title, sub, rowstate, win in [
    (16, "(a) Winner: row absent -> applied", "First LWT on a new handle. 4 round trips; trace duration 7.7 ms.",
     "row absent", True),
    (814, "(b) Loser: row present -> not applied", "Same handle again. Trace: 'CAS precondition does not match'.",
     "row present", False),
]:
    xs = panel(x0, title, sub, 760)
    phase(x0, 200, 150, "1 prepare / promise")
    msg(xs, "drv", "c1", 228, "INSERT ... IF NOT EXISTS", kind="cql")
    act(xs["c1"], 238, 168, "new ballot (timeuuid)")
    msg(xs, "c1", "c2", 296, "PAXOS_PREPARE_REQ")
    msg(xs, "c1", "c3", 312, "")
    msg(xs, "c2", "c1", 334, "PAXOS_PREPARE_RSP (promise)")
    phase(x0, 360, 110, "2 read current value (quorum)")
    msg(xs, "c1", "c2", 396, "read row")
    msg(xs, "c2", "c1", 434, rowstate)
    if win:
        act(xs["c1"], 446, 168, "condition holds", fill="#e3f4ec", stroke="#14724f")
    else:
        act(xs["c1"], 446, 200, "CAS precondition fails", fill="#fdf1f0", stroke=C["fault"])
    phase(x0, 490, 110, "3 propose / accept")
    msg(xs, "c1", "c2", 524, "PAXOS_PROPOSE_REQ" + (" (new row)" if win else " (empty update)"))
    msg(xs, "c1", "c3", 540, "")
    msg(xs, "c3", "c1", 576, "PAXOS_PROPOSE_RSP (accepted)")
    phase(x0, 620, 120, "4 commit" if win else "4 no commit")
    if win:
        msg(xs, "c1", "c2", 652, "PAXOS_COMMIT_REQ (normal write path)")
        msg(xs, "c1", "c3", 668, "")
        msg(xs, "c2", "c1", 698, "PAXOS_COMMIT_RSP")
        msg(xs, "c1", "drv", 726, "[applied] = True", kind="cql")
    else:
        s.text(xs["c1"] + 20, 664, "no PAXOS_COMMIT_REQ in the trace:", size=11.5, color=INK, weight="bold")
        s.text(xs["c1"] + 20, 680, "the empty proposal only closes this ballot", size=11, color=INK2)
        s.text(xs["c1"] + 20, 695, "(CASSANDRA-12126 fix for linearizable reads)", size=11, color=INK2)
        msg(xs, "c1", "drv", 726, "[applied] = False + current owner", kind="cql")

    s.text(x0 + 16, 790, "Every phase needs a majority (2 of 3); the coordinator is itself one of the acceptors.",
           size=11.5, color=INK2)
    if win:
        s.text(x0 + 16, 808, "A competing proposer with a higher ballot makes acceptors reject this one -> the "
               "loser retries;", size=11.5, color=INK2)
        s.text(x0 + 16, 824, "in-flight proposals found in a promise are re-proposed first (repair).", size=11.5,
               color=INK2)
    else:
        s.text(x0 + 16, 808, "Exp 6 race: 20 / 20 handles had exactly one winner; plain INSERTs at QUORUM "
               "acknowledged", size=11.5, color=INK2)
        s.text(x0 + 16, 824, "all 200 writes and 180 were silently overwritten by last-write-wins.", size=11.5,
               color=INK2)
    s.text(x0 + 16, 852, "Ordinary reads and writes never run these phases.", size=11.5, weight="bold", color=PAX)

s.save(sys.argv[1])
