"""Diagram - detailed sequence of one QUORUM write issued by workload/runner.py (actual functions)."""
import sys
from svgkit import SVG, C, INK, INK2, MUTED

W, H = 1600, 1200
s = SVG(W, H, "Detailed request sequence - Group 4")
s.text(W / 2, 32, "Sequence of one write: workload/runner.py -> app/db.py -> driver -> Cassandra -> CSV row",
       size=20, weight="bold", anchor="middle")
s.text(W / 2, 54, "Mode mixed, CL QUORUM, RF 3. Here the driver picked cass1 as coordinator; any replica can be "
       "picked. Solid = synchronous, dashed = asynchronous or reply.", size=13.5, color=INK2, anchor="middle",
       italic=True)

lanes = [
    ("w", "Worker thread", "workload/runner.py", "#2a78d6"),
    ("db", "app/db.py", "stmt, timed_execute", C["repl"]),
    ("drv", "Python driver", "cassandra-driver 3.29.3", C["repl"]),
    ("c1", "cass1", "coordinator + replica", C["gossip"]),
    ("c2", "cass2", "replica", C["gossip"]),
    ("c3", "cass3", "replica", C["gossip"]),
    ("log", "ResultsLog", "CSV on host via bind mount", "#6b6b66"),
]
X = {}
TOP, END = 92, 1170
for i, (k, t, sub, col) in enumerate(lanes):
    x = 105 + i * 232
    X[k] = x
    s.rect(x - 92, TOP, 184, 52, fill="#ffffff", stroke=col, sw=1.9, rx=7)
    s.text(x, TOP + 22, t, size=14, weight="bold", anchor="middle")
    s.text(x, TOP + 40, sub, size=11, color=INK2, anchor="middle")
    s.add(f'<path d="M{x},{TOP + 52} L{x},{END}" stroke="#bdbdb6" stroke-width="1.4" stroke-dasharray="4 4"/>')

# client container / cluster boundaries (behind lifeline heads)
s.add(f'<rect x="{X["w"] - 100}" y="{TOP - 14}" width="{X["drv"] - X["w"] + 200}" height="{END - TOP + 22}" rx="12" '
      f'fill="none" stroke="#2a78d6" stroke-width="1.3" stroke-dasharray="6 4"/>')
s.text(X["w"] - 92, TOP - 20, "client container", size=12, weight="bold", color="#2a78d6")
s.add(f'<rect x="{X["c1"] - 100}" y="{TOP - 14}" width="{X["c3"] - X["c1"] + 200}" height="{END - TOP + 22}" rx="12" '
      f'fill="none" stroke="{C["gossip"]}" stroke-width="1.3" stroke-dasharray="6 4"/>')
s.text(X["c1"] - 92, TOP - 20, "Cassandra cluster (peers, no master)", size=12, weight="bold", color=C["gossip"])


def msg(a, b, y, label, col, dashed=False, sub=None):
    x1, x2 = X[a], X[b]
    off = 6 if x2 > x1 else -6
    da = ' stroke-dasharray="8 5"' if dashed else ""
    mid = "q" + col.replace("#", "")
    s.add(f'<marker id="{mid}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
          f'<path d="M0,0 L10,5 L0,10 z" fill="{col}"/></marker>')
    s.add(f'<path d="M{x1 + off},{y} L{x2 - off},{y}" stroke="{col}" stroke-width="2"{da} marker-end="url(#{mid})"/>')
    w = len(label) * 6.1 + 8
    s.add(f'<rect x="{(x1 + x2) / 2 - w / 2:.0f}" y="{y - 19}" width="{w:.0f}" height="15" rx="3" fill="#ffffff" fill-opacity="0.95"/>')
    s.text((x1 + x2) / 2, y - 7, label, size=11.5, color=col, anchor="middle", weight="bold")
    if sub:
        s.text((x1 + x2) / 2, y + 15, sub, size=10.5, color=INK2, anchor="middle", italic=True)


def act(k, y, w, h, title, lines=(), fill="#fff6f0", stroke="#f0b08f", n=None):
    x = X[k] - w / 2
    s.rect(x, y, w, h, fill=fill, stroke=stroke, sw=1.4, rx=6)
    s.text(x + 8, y + 16, (f"{n}. " if n else "") + title, size=11.5, weight="bold")
    for i, ln in enumerate(lines):
        s.text(x + 8, y + 31 + i * 13.5, ln, size=10.5, color=INK2)


BLUE, ORG, GRN, GRY, RED = "#2a78d6", C["repl"], C["gossip"], "#6b6b66", C["fault"]
y = 176
act("w", y, 200, 58, "next_slot()", ["open loop: one slot every", "1/rate s; wait until it"], fill="#eef5fd",
    stroke="#9fbfe6", n=1)
y = 262
msg("w", "db", y, "2. stmt(INSERT_CQL, 'QUORUM')", BLUE)
act("db", y + 10, 200, 58, "cache lookup", ["first use: session.prepare()", "then CL fixed on the object"], n=3)
msg("db", "w", y + 84, "PreparedStatement (CL=QUORUM)", ORG, dashed=True)
y = 386
msg("w", "db", y, "4. timed_execute(ps, [room, uuid1(), 'runner', payload, run_id])", BLUE)
act("db", y + 10, 200, 44, "t0 = perf_counter()", n=5)
msg("db", "drv", y + 70, "6. session.execute_async(...)", ORG)
act("drv", y + 80, 214, 72, "route the request", ["routing key = room ->", "Murmur3 token -> replicas",
    "TokenAwarePolicy picks cass1"], n=7)
y = 562
msg("drv", "c1", y, "8. EXECUTE (stmt id, values, CL QUORUM)", ORG, sub="CQL native protocol, TCP 9042")
act("c1", y + 26, 214, 58, "live replicas >= 2?", ["gossip view: cass1-3 UP", "yes -> continue (else Unavailable)"],
    fill="#f1faf6", stroke="#8cc9ad", n=9)
act("c1", y + 92, 214, 44, "local write", ["commit log + memtable"], fill="#f1faf6", stroke="#8cc9ad", n=10)
y = 718
msg("c1", "c2", y, "11. MUTATION_REQ", GRN, dashed=True)
msg("c1", "c3", y + 22, "MUTATION_REQ (parallel)", GRN, dashed=True)
act("c2", y + 34, 190, 44, "commit log + memtable", [], fill="#f1faf6", stroke="#8cc9ad", n=12)
msg("c2", "c1", y + 104, "13. MUTATION_RSP (ack)", GRN, dashed=True, sub="cass1 + cass2 = 2 acks = QUORUM")
y = 862
msg("c1", "drv", y, "14. RESULT (void)", ORG, dashed=True)
msg("c3", "c1", y + 26, "MUTATION_RSP (late, not waited for)", GRN, dashed=True)
msg("drv", "db", y + 56, "15. future.result() returns", ORG, dashed=True)
act("db", y + 66, 214, 58, "OpResult", ["outcome='ok', latency_ms,", "coordinator=172.28.0.11"], n=16)
msg("db", "w", y + 146, "17. OpResult", ORG, dashed=True)
y = 1036
msg("w", "log", y, "18. _record(): log(op=write, cl=QUORUM, key=room, latency_ms, outcome=ok, coordinator)", GRY)
act("log", y + 10, 200, 44, "CSV row, flush()", n=19, fill="#f7f7f5", stroke="#b5b5ae")
act("w", y + 10, 200, 44, "Stats.record()", ["-> per-second line"], fill="#eef5fd", stroke="#9fbfe6", n=20)

# alt fragment (error paths)
fx, fy, fw, fh = X["drv"] - 108, 1078, X["c3"] - X["drv"] + 200, 88
s.rect(fx, fy, fw, fh, fill="#fff7f6", stroke=RED, sw=1.5, rx=6, dash="6 3")
s.add(f'<rect x="{fx}" y="{fy}" width="44" height="18" fill="{RED}"/>')
s.text(fx + 22, fy + 13, "alt", size=11.5, weight="bold", color="#ffffff", anchor="middle")
s.text(fx + 54, fy + 15, "error paths (no retry: FallthroughRetryPolicy; the row is still logged)", size=12,
       weight="bold", color=RED)
for i, ln in enumerate([
        "fewer than 2 live replicas at step 9 -> Unavailable -> outcome 'unavailable' (nothing written)",
        "fewer than 2 acks within 2 s -> WriteTimeout -> 'write_timeout' (write may still be applied)",
        "no reply within 5 s -> driver OperationTimedOut -> 'client_timeout';  no reachable node -> 'no_host'"]):
    s.text(fx + 12, fy + 36 + i * 16, ln, size=11.3, color=INK)

s.save(sys.argv[1])
