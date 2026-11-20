"""Figure D - fault injection and recovery lifecycle (Exp 3, 4, 5), with measured values and their source."""
import sys
from svgkit import SVG, C, INK, INK2, MUTED

W = 1600
s = SVG(W, 712, "Fault injection and recovery lifecycle - Group 4")
s.text(W / 2, 34, "Fault injection and recovery lifecycle (one node at a time, traffic running throughout)",
       size=20, weight="bold", anchor="middle")
s.text(W / 2, 56, "Green boxes: measured in our runs (source in brackets). Other text: documented Cassandra "
       "behaviour that the measurement is consistent with.", size=13.5, color=INK2, anchor="middle", italic=True)

stages = [
    ("1  Steady state", "#5b8fd0"),
    ("2  Inject fault", C["fault"]),
    ("3  Detection", C["gossip"]),
    ("4  Degraded service", "#d8a630"),
    ("5  Heal / restart", C["fault"]),
    ("6  Rejoin", C["gossip"]),
    ("7  Reconcile", C["repl"]),
    ("8  Verify", C["admin"]),
]
X0, CW, GAP = 142, 172, 6
cx = [X0 + i * (CW + GAP) for i in range(len(stages))]

# chevrons
for i, (t, col) in enumerate(stages):
    x = cx[i]
    pts = f"{x},80 {x + CW - 4},80 {x + CW + 12},102 {x + CW - 4},124 {x},124 {x + 16},102"
    if i == 0:
        pts = f"{x},80 {x + CW - 4},80 {x + CW + 12},102 {x + CW - 4},124 {x},124"
    s.add(f'<polygon points="{pts}" fill="{col}"/>')
    s.text(x + CW / 2 + 6, 107, t, size=13, weight="bold", color="#ffffff", anchor="middle")

rows = [
    ("Harness\n(host shell)", 138, 118, "#fdf1f0", C["fault"]),
    ("Cassandra\nmechanism", 264, 118, "#f1faf6", C["gossip"]),
    ("Client view\nper CL", 390, 96, "#eef5fd", C["cql"]),
    ("Measured\n(our runs)", 494, 170, "#e3f4ec", "#14724f"),
]
for label, y, h, fill, col in rows:
    s.rect(16, y, W - 32, h, fill=fill, stroke=col, sw=1.0, rx=10, opacity=0.55)
    s.text(28, y + 24, label, size=13, weight="bold", color=col)

cells = {
    0: [
        ["runner.py at fixed rate", "probe: 1 write + 1 read", "per CL every 250 ms", "3 phases logged:",
         "before / fault / after"],
        ["3 nodes UN, gossip", "heartbeats every second", "coordinator sends each", "write to all 3 replicas"],
        ["ONE, QUORUM, ALL all", "succeed", "", "W = R = 2 at QUORUM:", "R + W = 4 > N = 3"],
    ],
    1: [
        ["log_event -> UTC row in", "chaos_events.csv, then:", "docker kill (SIGKILL)", "docker stop (graceful)",
         "network disconnect", "(process keeps running)"],
        ["kill: no goodbye, peers", "just stop hearing it", "stop: node announces", "shutdown via gossip",
         "partition: both sides", "stop hearing each other"],
        ["requests that still go", "to the dead replica wait", "for a server timeout", "(write 2 s, read 5 s)"],
    ],
    2: [
        ["detect_down.py tails", "a peer's docker logs -t,", "matches 'is now DOWN'", "and subtracts the",
         "event time"],
        ["phi-accrual FD on each", "peer: convict at phi > 8", "(local decision, no vote,", "no leader election)",
         "status DN spreads by", "gossip"],
        ["ALL: WriteTimeout until", "conviction, then", "Unavailable at once", "ONE / QUORUM: still OK"],
    ],
    3: [
        ["traffic continues;", "second kill (3b) only", "after the first is", "detected"],
        ["coordinator skips DOWN", "replica, stores a hint", "for each missed write", "(window 3 h default)",
         "partition: minority side", "can reach only itself"],
        ["1 down: ONE, QUORUM ok", "ALL fails", "2 down: QUORUM fails", "minority side: ONE ok,",
         "QUORUM rejected"],
    ],
    4: [
        ["docker start cassN", "or docker network", "connect (heal)"],
        ["restart: new gossip", "generation, commit log", "replayed on startup", "heal: gossip resumes",
         "on both sides"],
        ["ALL keeps failing until", "the node is UP again"],
    ],
    5: [
        ["wait_for_all_un:", "peers report UN", "+ CQL ready check", "(hints_vs_repair.sh)"],
        ["peers mark node UP", "(phi drops); token", "ranges unchanged:", "no rebalancing,", "no re-election"],
        ["ALL recovers; first", "pinned reads may fail", "with no_host while", "driver pools reopen"],
    ],
    6: [
        ["Exp 4 isolates each", "path: 4a hints only,", "4b read repair only", "(handoff off), 4c full", "repair"],
        ["hint replay to the", "returning node; read", "repair on QUORUM/ALL", "digest mismatch;", "Merkle repair streams",
         "differing ranges; LWW"],
        ["ONE may read stale", "data from the returning", "node until repaired", "(observed, 4b)"],
    ],
    7: [
        ["verify_convergence.py:", "repair --full --preview", "(Merkle compare, no", "streaming) + read every",
         "acknowledged key at ALL"],
        ["IN SYNC = all replicas'", "Merkle trees equal for", "every range", "DIVERGENT = ranges", "that would stream"],
        ["converged when preview", "is IN SYNC and no", "acknowledged write is", "missing or wrong"],
    ],
}
for i, (h, m, cv) in cells.items():
    for r, lines in enumerate([h, m, cv]):
        y = rows[r][1] + 10
        for k, ln in enumerate(lines):
            s.text(cx[i] + 6, y + 16 + k * 15.5, ln, size=11.2, color=INK if k == 0 else INK2)

meas = {
    0: ["before every fault:", "100 % at all CLs", "[Exp 3, Exp 5,", "3 reps each]"],
    1: ["one node at a time;", "3a kill, 3b two kills,", "3c stop then kill,", "Exp 5 partition,",
        "Exp 4 kill [all logged", "in chaos_events.csv]"],
    2: ["kill: 19.6 s mean", "(18.9-22.2, n = 13)", "stop: 0.67 s (n = 3)", "partition: 19.2 s",
        "majority view, 18.7 s", "minority view (n = 4)", "[detection_times.csv]"],
    3: ["3a: ONE 100 %,", "QUORUM 100 %, ALL 4.7 %", "3b: QUORUM 60.1 %", "(fails after 2nd kill)",
        "Exp 5 minority: QUORUM", "rejected, ONE accepted", "[availability_phases]"],
    4: ["start to UP: 9.9 s", "mean (n = 16)", "[detection_times.csv]", "", "Exp 4: cass3 UN 8 s", "after start [log]"],
    5: ["after restart, ALL:", "3a 92.1 %, 3b 82.2 %", "(failures until UP)", "4a pinned reads:", "50 no_host (driver",
        "warm-up; fix written,", "not re-run) [Exp 4 log]"],
    6: ["4a: hint files 405 KB +", "425 KB drained 25 s", "after start", "4b: 50/50 read-repair", "traces; 17/17 stale",
        "before; 0/50 after", "Exp 5: higher timestamp", "won; ack'd write lost"],
    7: ["4a, 4c: preview IN SYNC", "5,000 / 5,000 and", "10,000 / 10,000 ack'd", "writes read back at ALL",
        "4b before repair:", "DIVERGENT 3,879", "ranges, 2.33 MB", "[Exp 4 run log]"],
}
for i, lines in meas.items():
    y = rows[3][1] + 10
    s.rect(cx[i] + 2, y, CW - 4, 20 + 15 * len(lines), fill="#ffffff", stroke="#14724f", sw=1.2, rx=6)
    for k, ln in enumerate(lines):
        s.text(cx[i] + 9, y + 18 + k * 15, ln, size=11, color="#14724f" if not ln.startswith("[") else MUTED,
               weight="bold" if k == 0 else "normal")

# bottom notes
s.text(28, 694, "No step involves leader election: Cassandra has no leader for ordinary reads and writes, so "
       "failure-detection time (column 3) is the quantity that replaces 're-election time' in the assignment.",
       size=12.5, color=INK, weight="bold")

s.save(sys.argv[1])
