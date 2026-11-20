"""Figure A - deployed system architecture with nested boundaries (what we actually ran)."""
import sys
from svgkit import SVG, C, INK2, MUTED

s = SVG(1600, 1040, "CassChat deployed system architecture - Group 4")

s.text(800, 34, "CassChat deployment as run for Experiments 1-6 (docker-compose.yml, Cassandra 5.0.8)",
       size=20, weight="bold", anchor="middle")
s.text(800, 56, "Peer-to-peer cluster: no master node. Any node coordinates any request; seeds only help gossip bootstrap.",
       size=13.5, color=INK2, anchor="middle", italic=True)

# ---------------------------------------------------------------- outer host boundary
s.boundary(18, 82, 1564, 944, "Host: Windows 11 laptop, WSL2 Ubuntu, Docker Desktop", "#f6f6f4", "#55554f")

# ---------------------------------------------------------------- host shell column
s.boundary(38, 120, 352, 700, "Host shell (bash, make, docker CLI)", "#fbfbfa", "#7a7a75", sw=1.3, size=13)

s.box(54, 145, 320, 98, "Experiment orchestration", [
    "Makefile targets: up, schema, smoke, exp1-exp6,",
    "verify, figures  (scripts/run_exp1.sh,",
    "chaos/run_exp3.sh, run_exp5.sh,",
    "recovery/hints_vs_repair.sh, run_exp6.sh)"], fill="#ffffff")

# fault-injection boundary
s.boundary(54, 272, 320, 236, "Fault injection (chaos/*.sh)", "#fdf1f0", C["fault"], dash="8 4", sw=1.6, size=13)
s.box(68, 296, 292, 200, "One node at a time, under traffic", [
    "kill_node.sh      docker kill --signal KILL",
    "stop_node.sh      docker stop --time 30",
    "start_node.sh     docker start",
    "partition.sh      docker network disconnect",
    "heal.sh           docker network connect",
    "pause_node.sh     docker pause (optional,",
    "                  not used in Exp 3/5)",
    "Each action -> results/logs/chaos_events.csv",
], fill="#ffffff", stroke=C["fault"], mono_lines=True, line_size=10.6)

# monitoring boundary
s.boundary(54, 538, 320, 266, "Monitoring and verification", "#f2f0fd", C["admin"], dash="3 3", sw=1.5, size=13)
s.box(68, 562, 292, 228, "Observers (no effect on data path)", [
    "detect_down.py: tails docker logs -t of a",
    "  peer, matches 'is now DOWN/UP',",
    "  detection time vs chaos_events.csv",
    "nodetool status / ring / getendpoints",
    "nodetool listpendinghints, hint-file bytes",
    "nodetool repair --full [--preview]",
    "  (verify_convergence.py, Exp 4)",
    "query traces (driver) for read repair",
    "  and Paxos phases (Exp 4b, Exp 6)",
], fill="#ffffff", stroke=C["admin"], line_size=11)

# ---------------------------------------------------------------- docker engine / network
s.boundary(410, 120, 1154, 700, "Docker engine (Compose project inft6000-hw3)", "#f3f7fc", "#3d6fa8", sw=1.4, size=13)
s.boundary(426, 160, 1122, 640, "Bridge network cassnet 172.28.0.0/16", "#ffffff", "#5b8fd0",
           dash="6 4", sw=1.3, size=12.5, sub="static node IPs; dynamic IPs from 172.28.1.0/24")

# client container
s.boundary(444, 200, 360, 580, "client container (profile tools)", "#eef5fd", C["cql"], sw=1.6, size=13)
s.text(456, 230, "python:3.11-slim, repo bind-mounted at /work", size=11.5, color=INK2, italic=True)
y = 244
for title, line in [
    ("workload/runner.py", "load generator: write | read | mixed, rate, CL"),
    ("app/chat.py", "CassChat CLI: rooms, post, read"),
    ("chaos/availability_probe.py", "1 write + 1 read per CL every 250 ms"),
    ("recovery/verify_convergence.py", "write / read-sample / acked check"),
    ("recovery/lwt_demo.py", "Exp 6: race, latency, trace"),
]:
    s.box(458, y, 332, 50, title, [line], fill="#ffffff", stroke="#9fbfe6", size=12, line_size=11)
    y += 58
s.box(458, 540, 332, 192, "DataStax Python driver 3.29.3", [
    "TokenAwarePolicy(DCAwareRoundRobin, dc1):",
    "  sends each request to a replica of the",
    "  partition, which acts as coordinator",
    "WhiteListRoundRobin for pinned reads (Exp 4)",
    "FallthroughRetryPolicy: no retries",
    "request timeout 5 s; no speculative exec.",
    "CL set per statement: ONE | QUORUM | ALL,",
    "  SERIAL for the LWT Paxos phase (Exp 6)",
], fill="#ffffff", stroke=C["cql"], sw=1.8, line_size=11.2)

# cluster boundary
s.boundary(826, 200, 704, 580, "Cassandra cluster inft6000-g4 - DC dc1 / rack1", "#f1faf6", C["gossip"], sw=1.7,
           size=13)
s.text(842, 232, "GossipingPropertyFileSnitch, Murmur3Partitioner, 16 vnodes per node", size=11.5, color=INK2,
       italic=True)
s.box(842, 244, 270, 92, "Keyspace chat", [
    "NetworkTopologyStrategy {dc1: 3}",
    "RF = N = 3: every partition on all 3 nodes",
    "tables: messages, room_state, usernames"], fill="#ffffff", stroke="#8cc9ad", size=12, line_size=11)

# token ring hint
s.add('<ellipse cx="1180" cy="530" rx="190" ry="150" fill="none" stroke="#b9dccb" stroke-width="10" '
      'stroke-opacity="0.55"/>')
s.text(1180, 540, "token ring", size=12, color="#5d9c80", anchor="middle", italic=True)
s.text(1180, 556, "(48 vnode tokens)", size=11, color="#5d9c80", anchor="middle", italic=True)

def node(x, y, name, ip, extra, seed):
    s.box(x, y, 196, 104, f"{name}", [ip, extra, "volume " + name + "-data"], fill="#ffffff",
          stroke=C["gossip"], sw=2.0, size=14, line_size=11.5)
    if seed:
        s.add(f'<rect x="{x + 124}" y="{y + 6}" width="62" height="18" rx="9" fill="#e3f4ec" stroke="#1b9a6c"/>')
        s.text(x + 155, y + 19, "seed", size=11, color="#14724f", anchor="middle", weight="bold")

node(1082, 300, "cass1", "172.28.0.11", "CQL 9042 also on 127.0.0.1", True)
node(866, 560, "cass2", "172.28.0.12", "internode :7000", True)
node(1302, 560, "cass3", "172.28.0.13", "internode :7000", False)
# optional cass4
s.box(1112, 680, 172, 84, "cass4 (optional)", ["172.28.0.14, profile scale", "Exp 1 join/decommission only"],
      fill="#fafafa", stroke=MUTED, dash="5 4", size=12, line_size=10.8)

# gossip edges (bidirectional, dashed green) along outer side of the triangle
s.edge([(1082, 360), (980, 360), (980, 560)], "gossip", both=True)
s.edge([(1278, 360), (1390, 360), (1390, 560)], "gossip", both=True)
s.edge([(1062, 650), (1302, 650)], "gossip", both=True, label="gossip 1 s rounds, phi-accrual FD", lx=1182, ly=640,
       lsize=11)
s.text(1450, 330, "gossip :7000", size=11.5, color=C["gossip"], weight="bold", anchor="middle")

# replication edges (orange) from example coordinator cass1 to other replicas
s.edge([(1120, 404), (1000, 560)], "repl", label="mutation /\nread (RF 3)", lx=1012, ly=470, lsize=11)
s.edge([(1240, 404), (1370, 560)], "repl")
s.text(1180, 450, "here cass1 coordinates;", size=11, color=C["repl"], weight="bold", anchor="middle")
s.text(1180, 465, "next request may use any node", size=11, color=C["repl"], weight="bold", anchor="middle")
s.text(1180, 480, "(per-request role, not a leader)", size=11, color=C["repl"], anchor="middle", italic=True)

# CQL edges client driver -> each node
s.edge([(790, 570), (830, 570), (830, 352), (1082, 352)], "cql", label="CQL :9042", lx=900, ly=344, lsize=11.5)
s.edge([(790, 610), (866, 610)], "cql")
s.edge([(790, 712), (850, 712), (850, 790), (1400, 790), (1400, 664)], "cql",
       label="driver connects to every node (any can coordinate)", lx=1125, ly=786, lsize=11)

# chaos -> cluster (fault injection)
s.edge([(374, 330), (400, 330), (400, 104), (1470, 104), (1470, 200)], "fault",
       label="docker kill | stop | start | network disconnect/connect  cassN", lx=930, ly=100, lsize=11.5)

# admin/monitoring -> cluster
s.edge([(374, 700), (396, 700), (396, 838), (1500, 838), (1500, 780)], "admin",
       label="docker exec cassN nodetool ... / cqlsh;  docker logs -t cassN", lx=950, ly=834, lsize=11.5)

# orchestration -> client container (docker compose run)
s.edge([(374, 222), (444, 222)], "admin")
# orchestration -> chaos
s.edge([(214, 243), (214, 272)], "admin")

# ---------------------------------------------------------------- results (host filesystem)
s.boundary(410, 872, 1154, 136, "Results on host filesystem (bind-mounted into client at /work/results)", "#f7f7f5",
           C["file"], dash="2 3", sw=1.4, size=13)
cols = [
    ("results/raw/expN/*.csv", ["one row per operation: time, CL, op,", "outcome, error type, latency, coordinator"]),
    ("results/logs/", ["chaos_events.csv, per-run nodetool logs,", "detection.csv, traces, preview output"]),
    ("results/summary/, figures/", ["analysis/summarize.py + plots.py:", "runs, groups, phases, detection, PNGs"]),
    ("docs/report/generated/", ["LaTeX macros and tables generated", "from the CSVs (no hand-typed numbers)"]),
]
x = 428
for t, ls in cols:
    s.box(x, 900, 272, 92, t, ls, fill="#ffffff", stroke="#b5b5ae", size=12, line_size=11, mono_lines=False)
    x += 282
s.edge([(620, 780), (620, 900)], "file", label="CSV per op", lx=628, ly=846, lsize=11, anchor="start")

# ---------------------------------------------------------------- legend
s.legend(38, 836, [
    ("cql", "client CQL request (port 9042)"),
    ("repl", "coordinator-to-replica data traffic"),
    ("gossip", "gossip / failure detection (7000)"),
    ("fault", "fault injection (Docker API)"),
    ("admin", "control: compose run, docker exec"),
    ("file", "file output (CSV, logs)"),
], title="Edge types", w=352)

s.save(sys.argv[1])
