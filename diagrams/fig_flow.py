"""Figure C - request flows: QUORUM write with a replica down (hint) and ALL read with read repair."""
import sys
from svgkit import SVG, C, INK, INK2, MUTED

s = SVG(1600, 960, "Cassandra read and write request flows - Group 4")
s.text(800, 34, "Request flows on the CassChat cluster (RF = 3, coordinator chosen per request, no leader)",
       size=20, weight="bold", anchor="middle")
s.text(800, 56, "Message names follow Cassandra 5.0 query traces. Numbers in green boxes were observed in our "
       "Exp 4 run; everything else is the documented mechanism.", size=13.5, color=INK2, anchor="middle",
       italic=True)


def panel(x0, title, sub, lanes, top=92, height=846, life_end=None):
    s.boundary(x0, top, 770, height, title, "#fbfbfa", "#3d3d39", sw=1.5, size=14)
    s.text(x0 + 16, top + 30, sub, size=12, color=INK2, italic=True)
    xs = {}
    for i, (key, label, sub2, col) in enumerate(lanes):
        cx = x0 + 90 + i * 196
        xs[key] = cx
        s.rect(cx - 78, top + 46, 156, 50, fill="#ffffff", stroke=col, sw=1.8, rx=7)
        s.text(cx, top + 66, label, size=13, weight="bold", anchor="middle")
        s.text(cx, top + 84, sub2, size=11, color=INK2, anchor="middle")
        s.add(f'<path d="M{cx},{top + 96} L{cx},{life_end or top + height - 14}" stroke="#bdbdb6" stroke-width="1.4" '
              f'stroke-dasharray="4 4"/>')
    return xs


def msg(xs, a, b, y, label, kind="repl", dash_label=False, sub=None):
    x1, x2 = xs[a], xs[b]
    off = 6 if x2 > x1 else -6
    s.edge([(x1 + off, y), (x2 - off, y)], kind, label=label, lx=(x1 + x2) / 2, ly=y - 7, lsize=11.3)
    if sub:
        s.text((x1 + x2) / 2, y + 15, sub, size=10.5, color=INK2, anchor="middle", italic=True)


def act(x, y, w, h, title, lines=(), fill="#fff6f0", stroke="#f0b08f"):
    s.box(x - w / 2, y, w, h, title, lines, fill=fill, stroke=stroke, size=11.5, line_size=10.6)


def obs(x, y, w, lines):
    s.box(x, y, w, 30 + 14 * len(lines), "Observed (Exp 4, run 20261119T073818Z)", lines, fill="#e3f4ec",
          stroke="#14724f", size=11.3, line_size=10.6)


# ======================================================== panel A: write
A = panel(16, "(a) Write at QUORUM while cass3 is DOWN -> hinted handoff",
          "W = 2 of RF = 3. Coordinator = the node the token-aware driver picked (here cass1).",
          [("drv", "Driver", "client container", C["cql"]),
           ("c1", "cass1", "coordinator + replica", C["gossip"]),
           ("c2", "cass2", "replica", C["gossip"]),
           ("c3", "cass3", "replica (killed)", C["fault"])], life_end=730)
y = 220
msg(A, "drv", "c1", y, "INSERT ... (CL QUORUM)", kind="cql")
act(A["c1"], y + 14, 170, 50, "local write", ["commit log + memtable"])
s.add(f'<rect x="{A["c3"] - 70}" y="{y - 30}" width="140" height="112" rx="6" fill="#fdf1f0" '
      f'stroke="{C["fault"]}" stroke-dasharray="6 3"/>')
s.text(A["c3"], y - 12, "DOWN", size=13, weight="bold", color=C["fault"], anchor="middle")
s.text(A["c3"], y + 4, "docker kill; peers'", size=10.5, color=INK2, anchor="middle")
s.text(A["c3"], y + 18, "phi detector convicts", size=10.5, color=INK2, anchor="middle")
s.text(A["c3"], y + 32, "it after ~20 s", size=10.5, color=INK2, anchor="middle")
msg(A, "c1", "c2", y + 92, "MUTATION_REQ")
s.edge([(A["c1"] + 6, y + 128), (A["c3"] - 74, y + 128)], "fault", label="not sent: cass3 marked DOWN",
       lx=(A["c1"] + A["c3"]) / 2 + 40, ly=y + 121, lsize=11)
act(A["c1"], y + 140, 176, 50, "store hint for cass3", ["hints dir, window 3 h"], fill="#fff4dc", stroke="#d8a630")
msg(A, "c2", "c1", y + 214, "MUTATION_RSP (ack)")
s.text(A["c1"] - 92, y + 248, "2 acks (cass1 + cass2) >= W = 2", size=11.3, weight="bold", color=INK)
msg(A, "c1", "drv", y + 270, "success", kind="cql")
s.text(A["drv"] + 4, y + 292, "write acknowledged", size=10.5, color=INK2, italic=True)

# recovery part
s.add(f'<path d="M{A["drv"] - 74},{y + 318} L{A["c3"] + 80},{y + 318}" stroke="#9a9a94" stroke-width="1" '
      f'stroke-dasharray="2 3"/>')
s.text(A["drv"] - 72, y + 336, "later: docker start cass3", size=11.5, weight="bold", color=INK2)
msg(A, "c3", "c1", y + 368, "gossip: cass3 is UP", kind="gossip")
msg(A, "c1", "c3", y + 412, "HINT_REQ (replay stored mutations)")
msg(A, "c3", "c1", y + 452, "HINT_RSP", kind="repl")
act(A["c1"], y + 466, 170, 36, "delete hint file", [], fill="#fff4dc", stroke="#d8a630")
obs(A["drv"] - 74, y + 520, 588, [
    "5,000 / 5,000 writes acknowledged at QUORUM with cass3 down",
    "hint files on cass1 / cass2: 405,248 B / 424,836 B; listpendinghints printed nothing",
    "cass3 UN 8 s after start; hint files drained 25 s after start",
    "Merkle preview afterwards: IN SYNC; 5,000 / 5,000 values read back at ALL"])
s.text(A["drv"] - 74, y + 640, "Failure branches (documented): fewer than 2 live replicas -> Unavailable, nothing written;",
       size=11, color=INK2)
s.text(A["drv"] - 74, y + 656, "live but slow replica -> WriteTimeout after 2 s, and the write may still be applied", size=11,
       color=INK2)
s.text(A["drv"] - 74, y + 672, "(Cassandra does not roll back). Hints stop after max_hint_window; repair covers the rest.",
       size=11, color=INK2)

# ======================================================== panel B: read
B = panel(814, "(b) Read at ALL through the stale replica -> blocking read repair",
          "Exp 4b: handoff disabled, cass3 missed 5,000 writes. Reads pinned to cass3 as coordinator.",
          [("drv", "Driver", "pinned to cass3", C["cql"]),
           ("c3", "cass3", "coordinator, stale", C["gossip"]),
           ("c1", "cass1", "replica", C["gossip"]),
           ("c2", "cass2", "replica", C["gossip"])], life_end=770)
y = 220
msg(B, "drv", "c3", y, "SELECT ... (CL ALL)", kind="cql")
act(B["c3"], y + 14, 170, 50, "local data read", ["memtable + SSTables (old)"])
msg(B, "c3", "c1", y + 96, "READ_REQ (digest only)")
msg(B, "c3", "c2", y + 130, "READ_REQ (digest only)")
msg(B, "c1", "c3", y + 166, "digest")
msg(B, "c2", "c3", y + 200, "digest")
act(B["c3"], y + 214, 176, 36, "Digest mismatch", [], fill="#fdf1f0", stroke=C["fault"])
msg(B, "c3", "c1", y + 280, "READ_REQ (full data)")
msg(B, "c3", "c2", y + 312, "READ_REQ (full data)")
msg(B, "c1", "c3", y + 346, "data")
msg(B, "c2", "c3", y + 378, "data (newer timestamps)")
act(B["c3"], y + 392, 176, 50, "resolve per cell", ["highest timestamp wins (LWW)"])
s.edge([(B["c3"] + 88, y + 466), (B["c3"] + 130, y + 466), (B["c3"] + 130, y + 490), (B["c3"] + 6, y + 490)], "repl",
       label="read-repair mutation", lx=B["c3"] + 136, ly=y + 474, lsize=11.3, anchor="start")
s.text(B["c3"] + 136, y + 504, "to every stale replica (here cass3", size=10.5, color=INK2, italic=True)
s.text(B["c3"] + 136, y + 518, "itself); waits for the ack (blocking)", size=10.5, color=INK2, italic=True)
msg(B, "c3", "drv", y + 536, "newest row", kind="cql")
obs(B["drv"] - 74, y + 568, 588, [
    "Merkle preview after restart: DIVERGENT, 3,879 ranges, 2,333,082 B to stream",
    "ONE via cass3 before repair: 17 of 17 answers served by cass3 were stale (28 no_host)",
    "ALL via cass3: 50 / 50 traces show 'Digest mismatch' + 'read-repair-mutation'",
    "ONE afterwards: 0 / 50 stale; untouched control keys: 50 / 50 still stale",
    "preview still DIVERGENT (4,050 ranges): read repair fixes only keys that are read",
    "nodetool repair --full -> preview IN SYNC; 10,000 / 10,000 values read back at ALL"])

s.save(sys.argv[1])
