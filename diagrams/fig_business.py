"""Diagram - complete business flow of one operation, from the operator to the report (actual code paths)."""
import sys
from xml.sax.saxutils import escape
from svgkit import SVG, C, INK, INK2, MUTED

s = SVG(1600, 1080, "CassChat complete business flow - Group 4")
s.text(800, 32, "Business flow of one operation: from the command we type to the number in the report",
       size=20, weight="bold", anchor="middle")
s.text(800, 54, "Solid arrow = synchronous call that waits for an answer.  Dashed arrow = asynchronous / runs in "
       "parallel.  Diamonds = decisions that change the outcome.", size=13.5, color=INK2, anchor="middle",
       italic=True)

COL = {"ctl": C["admin"], "app": "#2a78d6", "db": C["repl"], "res": "#6b6b66", "fault": C["fault"],
       "gos": C["gossip"]}


def arrow(pts, col, dashed=False, label=None, lx=None, ly=None, anchor="middle", size=11.5, sw=2.0):
    d = "M" + " L".join(f"{x},{y}" for x, y in pts)
    da = ' stroke-dasharray="8 5"' if dashed else ""
    mid = col.replace("#", "")
    s.add(f'<marker id="m{mid}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
          f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{col}"/></marker>')
    s.add(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="{sw}"{da} marker-end="url(#m{mid})" '
          f'stroke-linejoin="round"/>')
    if label:
        if lx is None:
            (x1, y1), (x2, y2) = pts[0], pts[1]
            lx, ly = (x1 + x2) / 2, (y1 + y2) / 2 - 6
        lines = label.split("\n")
        w = max(len(t) for t in lines) * size * 0.53 + 8
        bx = lx - w / 2 if anchor == "middle" else (lx - 4 if anchor == "start" else lx - w + 4)
        s.add(f'<rect x="{bx:.0f}" y="{ly - size - 1:.0f}" width="{w:.0f}" height="{len(lines) * size * 1.25 + 4:.0f}" '
              f'rx="3" fill="#ffffff" fill-opacity="0.95"/>')
        s.text(lx, ly, label, size=size, color=col, anchor=anchor, weight="bold")


def diamond(cx, cy, w, h, text, col):
    s.add(f'<polygon points="{cx},{cy - h / 2} {cx + w / 2},{cy} {cx},{cy + h / 2} {cx - w / 2},{cy}" '
          f'fill="#fffbea" stroke="{col}" stroke-width="1.8"/>')
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        s.text(cx, cy - (len(lines) - 1) * 7.5 + i * 15 + 4, ln, size=12, anchor="middle", weight="bold")


def step(x, y, w, h, n, title, lines, stroke, fill="#ffffff"):
    s.rect(x, y, w, h, fill=fill, stroke=stroke, sw=1.8, rx=8)
    s.add(f'<circle cx="{x + 17}" cy="{y + 17}" r="12" fill="{stroke}"/>')
    s.text(x + 17, y + 21.5, str(n), size=12.5, weight="bold", color="#ffffff", anchor="middle")
    s.text(x + 36, y + 22, title, size=13.5, weight="bold")
    for i, ln in enumerate(lines):
        mono = ln.startswith("`")
        s.text(x + 12, y + 44 + i * 15.5, ln.replace("`", ""), size=11.0 if mono else 11.3, color=INK2, mono=mono)


# ---------------------------------------------------------------- boundaries
s.boundary(16, 84, 262, 700, "Host shell (WSL2)", "#f7f5fd", C["admin"], sw=1.5, size=13)
s.boundary(296, 84, 560, 700, "client container (Python 3.11)", "#eef5fd", "#2a78d6", sw=1.6, size=13)
s.boundary(876, 84, 708, 700, "Cassandra cluster (cass1-cass3, RF 3)", "#f1faf6", C["gossip"], sw=1.6, size=13)
s.boundary(16, 816, 1568, 248, "Results on the host filesystem (bind mount /work/results)", "#f7f7f5",
           "#6b6b66", dash="3 3", sw=1.4, size=13)

# ---------------------------------------------------------------- host column
step(30, 118, 234, 120, 1, "Operator starts it", ["`make exp3 VARIANT=3a`", "`make demo-exp2`, or the CLI:",
     "`python -m app.chat post ...`", "(Makefile target)"], C["admin"])
step(30, 262, 234, 172, 2, "Orchestrator script", ["`chaos/run_exp3.sh` etc.:", "wait_for_cluster.sh (3 x UN)",
     "docker compose run client", "  python -m workload.runner", "starts probe in parallel",
     "records chaos events"], C["admin"])
step(30, 458, 234, 152, "F", "Fault injection", ["`chaos/kill_node.sh cass3`", "log_event -> chaos_events.csv",
     "docker kill / stop / start", "network disconnect / connect", "(parallel to the traffic)"], C["fault"],
     fill="#fff7f6")
step(30, 634, 234, 132, "M", "Monitoring", ["`chaos/detect_down.py`:", "docker logs -t of a peer,",
     "'is now DOWN/UP' minus", "event time"], C["admin"], fill="#fbfaff")

# ---------------------------------------------------------------- client container column
step(312, 118, 528, 104, 3, "Entry point and validation", [
    "`workload/runner.py main()`: build_parser(), resolve_args()",
    "--cl checked by _cl() -> app.db.cl_value() (unknown CL = exit)",
    "get_session(): Cluster(contact_points = 3 node IPs).connect('chat')"], "#2a78d6")
step(312, 244, 528, 120, 4, "Business logic (one operation)", [
    "Runner.worker: open-loop slot every 1/rate s (OpenLoopSchedule)",
    "do_write: random room, msg_id = uuid1(), payload, run_id",
    "do_read: random room, newest --read-limit messages",
    "do_probe: write seq n via node A, read it back via node B"], "#2a78d6")
step(312, 386, 528, 104, 5, "Data access: app/db.py", [
    "stmt(cql, cl): prepared statement cached per (cql, CL), CL fixed",
    "timed_execute(): execute_async + future.result(), never raises",
    "returns OpResult(outcome, error_type, latency_ms, coordinator)"], C["repl"])
step(312, 512, 528, 120, 6, "DataStax driver 3.29.3", [
    "routing key = room -> Murmur3 token -> the 3 replicas",
    "TokenAwarePolicy picks a replica as coordinator (or pinned",
    "node: WhiteListRoundRobinPolicy); FallthroughRetryPolicy;",
    "request_timeout 5 s; CQL native protocol over TCP :9042"], C["repl"])
step(312, 654, 528, 112, 12, "Classify and record", [
    "classify_error(): ok | unavailable | write_timeout | read_timeout",
    "  | write_failure | read_failure | no_host | client_timeout | other",
    "Runner._record(): Stats (per-second line) + ResultsLog row"], "#6b6b66")

# ---------------------------------------------------------------- cluster column
diamond(1020, 168, 248, 108, "7  Enough live\nreplicas for CL?", C["gossip"])
s.text(1152, 196, "decided from the coordinator's own", size=11, color=INK2, italic=True)
s.text(1152, 210, "gossip view, before any replica is asked", size=11, color=INK2, italic=True)
step(900, 262, 270, 128, 8, "Coordinator fans out", ["write: mutation to ALL live", "replicas (W only sets how",
     "many acks to wait for)", "read: data + R-1 digests"], C["gossip"])
step(1200, 262, 370, 128, 9, "Each replica (cass1-3)", ["write: commit log append + memtable,",
     "then ack; hint stored for a DOWN replica", "read: memtable + SSTables merged by",
     "timestamp; data or digest returned"], C["gossip"])
diamond(1035, 488, 270, 112, "10  W acks (or R replies)\nwithin 2 s / 5 s?", C["gossip"])
step(1200, 438, 370, 104, "RR", "Read only: digests differ?", ["full data reads, newest cell wins (LWW),",
     "blocking read-repair mutation to stale", "replicas, then answer"], C["gossip"], fill="#f6fbf8")
step(900, 600, 670, 166, 11, "Result back to the driver", [
    "success: RESULT frame (rows for a read, void for a write)",
    "no: Unavailable error, nothing written (decided before any replica is contacted)",
    "timeout: WriteTimeout / ReadTimeout. For a write this means UNKNOWN, not failed:",
    "replicas that applied it keep it (no rollback)",
    "no reply in 5 s: driver raises OperationTimedOut (client_timeout)"], C["gossip"])

# ---------------------------------------------------------------- results row
step(34, 846, 360, 196, 13, "Per-operation CSV row", ["`app/results_log.py ResultsLog.log()`",
     "results/raw/<exp>/<exp>_<variant>_<cl>_r<rep>.csv", "ts_utc, op, cl, key, latency_ms,",
     "outcome, error_type, expected/observed", "seq, stale, coordinator", "flushed per row; never overwritten",
     "only rows in the measured window"], "#6b6b66")
step(420, 846, 360, 196, 14, "Live and final summary", ["Runner.reporter(): one line per second",
     "(ops/s, ok, err, p50, p99)", "Runner.summary(): p50/p95/p99,", "throughput, errors by type, stale %",
     "exit code 0, or 3 if nothing succeeded"], "#6b6b66")
step(806, 846, 380, 196, 15, "Analysis pipeline", ["`analysis/summarize.py` + `plots.py`",
     "(make figures): newest run per scenario,", "phases split at chaos_events.csv",
     "-> results/summary/*.csv, summary.md", "-> results/figures/*.png",
     "-> docs/report/generated/*.tex"], "#6b6b66")
step(1212, 846, 358, 196, 16, "Report and slides", ["Tables and charts in the report and", "deck come from step 15, so every",
     "number traces back to CSV rows", "", "Exp 4 / Exp 6 extra checks:", "verify_convergence.py, lwt_demo.py",
     "write their own CSVs the same way"], "#6b6b66")

# ---------------------------------------------------------------- arrows
arrow([(147, 238), (147, 262)], COL["ctl"])
arrow([(264, 300), (281, 300), (281, 150), (312, 150)], COL["ctl"])
arrow([(147, 434), (147, 458)], COL["fault"], dashed=True)
arrow([(264, 480), (287, 480), (287, 70), (1400, 70), (1400, 262)], COL["fault"], dashed=True,
      label="docker kill cass3 (async, while traffic runs)", lx=1120, ly=74, size=10.5)
arrow([(147, 610), (147, 634)], COL["ctl"], dashed=True)
arrow([(576, 222), (576, 244)], COL["app"])
arrow([(576, 364), (576, 386)], COL["app"])
arrow([(576, 490), (576, 512)], COL["db"])
arrow([(840, 560), (870, 560), (870, 168), (896, 168)], COL["db"],
      label="EXECUTE (stmt id, values, CL)", lx=880, ly=250, size=10.5, anchor="start")
arrow([(1020, 222), (1020, 262)], COL["gos"])
arrow([(1144, 168), (1580, 168), (1580, 640), (1570, 640)], COL["fault"],
      label="no: Unavailable", lx=1460, ly=162, size=11.5)
arrow([(1170, 326), (1200, 326)], COL["gos"], dashed=True)
arrow([(1300, 390), (1300, 410), (1100, 410), (1060, 438)], COL["gos"], label="acks / data / digests",
      lx=1200, ly=405, size=10.5)
arrow([(1170, 488), (1200, 488)], COL["gos"], label="read", lx=1186, ly=480, size=10)
arrow([(1035, 544), (1035, 600)], COL["gos"], label="yes / no -> timeout", lx=1035, ly=580, size=11)
arrow([(900, 700), (856, 700), (856, 595), (840, 595)], COL["db"],
      label="RESULT or error frame", lx=846, ly=660, size=10.5, anchor="end")
arrow([(576, 632), (576, 654)], COL["db"], label="OpResult", lx=620, ly=648, size=10.5)
arrow([(400, 766), (214, 846)], COL["res"])
arrow([(620, 766), (600, 846)], COL["res"])
arrow([(780, 940), (806, 940)], COL["res"], dashed=True)
s.text(793, 930, "later", size=10, color=MUTED, anchor="middle", italic=True)
arrow([(1186, 940), (1212, 940)], COL["res"])
arrow([(264, 700), (290, 700), (290, 800), (806, 800), (806, 870)], COL["ctl"], dashed=True,
      label="detection_times.csv", lx=650, ly=804, size=10.5)

s.save(sys.argv[1])
