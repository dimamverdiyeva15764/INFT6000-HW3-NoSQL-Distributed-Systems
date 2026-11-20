"""Figure B - inside one Cassandra 5.0 node: coordinator role, storage engine, cluster services."""
import sys
from svgkit import SVG, C, INK, INK2, MUTED

s = SVG(1600, 1000, "Cassandra node internals - Group 4")
s.text(800, 34, "Inside one Cassandra 5.0.8 node (all three nodes are identical: there is no special master node)",
       size=20, weight="bold", anchor="middle")
s.text(800, 56, "Every node plays two roles per request: coordinator (if the driver picked it) and local replica "
       "(if it owns the token range; with RF = N = 3, every node owns every row).",
       size=13.5, color=INK2, anchor="middle", italic=True)

V_FILL, V_STROKE = "#e3f4ec", "#14724f"
D_FILL, D_STROKE = "#f0f0ee", "#6b6b66"


def badge(x, y, kind, text):
    fill, stroke = (V_FILL, V_STROKE) if kind == "V" else (D_FILL, D_STROKE)
    w = 10 + len(text) * 6.0
    s.add(f'<rect x="{x}" y="{y}" width="{w:.0f}" height="17" rx="8.5" fill="{fill}" stroke="{stroke}"/>')
    s.text(x + w / 2, y + 12.5, text, size=10.5, color=stroke, anchor="middle", weight="bold")


# ------------------------------------------------------------------ client
s.box(24, 150, 170, 120, "Client (driver)", ["token-aware routing", "CL per statement", "SERIAL for LWT"],
      fill="#eef5fd", stroke=C["cql"], sw=1.8, size=13, line_size=11.5)

# ------------------------------------------------------------------ node boundary
s.boundary(220, 90, 1050, 880, "Node cass1 (172.28.0.11) - same software on cass2, cass3", "#fbfbfa", "#3d3d39",
           sw=1.8, size=14)

# coordinator role
s.boundary(244, 130, 560, 262, "Coordinator role (per request)", "#eef5fd", C["cql"], sw=1.5, size=13)
s.box(260, 156, 528, 72, "Native transport  :9042  (CQL protocol v5)", [
    "parses statement, reads its consistency level, picks request path"], fill="#ffffff", stroke="#9fbfe6",
      size=12.5, line_size=11.3)
s.box(260, 238, 258, 142, "Replica selection", [
    "token = Murmur3(partition key)",
    "walk ring of 48 vnode tokens",
    "NetworkTopologyStrategy dc1:3",
    "-> replicas {cass1, cass2, cass3}",
    "snitch orders replicas for reads"], fill="#ffffff", stroke="#9fbfe6", size=12.5, line_size=11.2)
badge(420, 242, "V", "Exp 1")
s.box(530, 238, 258, 142, "Consistency accounting", [
    "write: send to all live replicas,",
    "  reply after W acks (2 s timeout)",
    "read: data + digest requests,",
    "  reply after R answers (5 s timeout)",
    "too few live replicas -> Unavailable"], fill="#ffffff", stroke="#9fbfe6", size=12.5, line_size=11.2)
badge(700, 242, "V", "Exp 2,3,5")

# storage engine (local replica role)
s.boundary(244, 424, 560, 530, "Local replica role: storage engine (LSM tree)", "#fff6f0", C["repl"], sw=1.5,
           size=13)
s.text(258, 452, "write path", size=12.5, weight="bold", color=C["repl"])
s.box(258, 462, 250, 92, "1. Commit log", ["append-only, on disk", "replayed after a crash", "sync mode: periodic (default)"],
      fill="#ffffff", stroke="#f0b08f", size=12.5, line_size=11.2)
badge(420, 466, "V", "trace")
s.box(540, 462, 250, 92, "2. Memtable", ["in memory, sorted by key", "one per table", "write acked after 1 + 2"],
      fill="#ffffff", stroke="#f0b08f", size=12.5, line_size=11.2)
badge(702, 466, "V", "trace")
s.edge([(508, 508), (540, 508)], "repl")
s.box(258, 600, 532, 106, "3. SSTables (immutable, flushed from memtable)", [
    "Data, Partition index, Bloom filter, statistics; each cell carries a write timestamp",
    "deletes are tombstones (kept gc_grace_seconds = 10 days by default)",
    "compaction merges SSTables, keeps newest cell, later purges expired tombstones"],
      fill="#ffffff", stroke="#f0b08f", size=12.5, line_size=11.2)
badge(700, 604, "V", "trace")
badge(612, 604, "D", "compaction")
s.edge([(665, 554), (665, 600)], "repl", label="flush", lx=690, ly=582, lsize=11, anchor="start")

s.text(258, 738, "read path", size=12.5, weight="bold", color=C["repl"])
s.box(258, 748, 532, 92, "Merge memtable + SSTables", [
    "Bloom filter skips SSTables that cannot hold the key (seen in our Paxos trace)",
    "cells merged by timestamp: last write wins per cell",
    "returns full data or an MD5 digest, as the coordinator asked"], fill="#ffffff", stroke="#f0b08f",
      size=12.5, line_size=11.2)
badge(700, 752, "V", "trace")

s.box(258, 856, 532, 84, "Paxos state  (system.paxos table, only for LWT)", [
    "per partition: promised ballot, accepted proposal, most recent commit",
    "written through the same commit log + memtable path"], fill="#ffffff", stroke="#d8b4e8", size=12.5,
      line_size=11.2)
badge(700, 860, "V", "Exp 6")

# cluster services
s.boundary(828, 130, 422, 824, "Cluster services (run on every node)", "#f1faf6", C["gossip"], sw=1.5, size=13)
svc = [
    ("Messaging service  :7000", ["internode TCP: mutations, reads, digests,",
                                  "gossip, Paxos, repair messages"], "V", "trace"),
    ("Gossiper", ["every second: exchange versioned endpoint", "state (heartbeat, status, schema, tokens)",
                  "with a random live peer; seeds aid bootstrap"], "V", "Exp 1,3,5"),
    ("Failure detector (phi-accrual)", ["suspicion phi from heartbeat inter-arrival",
                                        "convict at phi > 8 -> peer marked DOWN",
                                        "local opinion, not a cluster vote"], "V", "Exp 3,5"),
    ("Hints store  /var/lib/cassandra/hints", ["coordinator keeps a write for a DOWN replica",
                                                "replays it when gossip says UP",
                                                "only within max_hint_window (3 h default)"], "V", "Exp 4a"),
    ("Read repair (blocking)", ["on digest mismatch at QUORUM/ALL: resolve",
                                "by timestamp, push newest cells to stale",
                                "replicas before replying"], "V", "Exp 4b"),
    ("Anti-entropy repair (nodetool repair)", ["Merkle tree per token range per replica",
                                               "compare trees, stream only differing ranges",
                                               "--preview: compare without streaming"], "V", "Exp 4"),
    ("Paxos (LWT only, Paxos v1 here)", ["prepare/promise, read, propose/accept,",
                                         "commit; quorum of the partition's replicas",
                                         "plain reads and writes never use Paxos"], "V", "Exp 6"),
]
y = 156
for t, ls, k, b in svc:
    h = 24 + len(ls) * 15 + 12
    s.box(842, y, 394, h, t, ls, fill="#ffffff", stroke="#8cc9ad", size=12.5, line_size=11.2)
    badge(1236 - 10 - (10 + len(b) * 6.0), y + 5, k, b)
    y += h + 12

# ------------------------------------------------------------------ peers
for i, (n, ip) in enumerate([("cass2", "172.28.0.12"), ("cass3", "172.28.0.13")]):
    yy = 300 + i * 330
    s.box(1310, yy, 268, 150, f"{n}  ({ip})", ["same components", "replica for every row (RF 3)",
                                               "can coordinate any request", "gossip peer"],
          fill="#ffffff", stroke=C["gossip"], sw=1.8, size=13.5, line_size=11.5)

# edges
s.edge([(194, 200), (260, 200)], "cql", label="CQL", lx=227, ly=192, lsize=11)
s.edge([(804, 165), (816, 165), (816, 110), (1290, 110), (1290, 340), (1310, 340)], "repl",
       label="mutation / read / digest / Paxos messages to the other replicas", lx=1050, ly=106, lsize=11.5)
s.edge([(1290, 340), (1290, 680), (1310, 680)], "repl")
s.edge([(1236, 250), (1270, 250), (1270, 400), (1310, 400)], "gossip", both=True)
s.edge([(1270, 400), (1270, 730), (1310, 730)], "gossip", both=True)
s.text(1386, 482, "gossip + FD", size=11.5, color=C["gossip"], weight="bold", anchor="middle")
s.text(1386, 498, "heartbeats both ways", size=11, color=C["gossip"], anchor="middle")
s.edge([(788, 330), (812, 330), (812, 500), (260 + 532, 500)], "repl")  # coordinator -> local storage
s.text(816, 412, "local", size=10.5, color=C["repl"], weight="bold")
s.text(816, 425, "write", size=10.5, color=C["repl"], weight="bold")

# legend
s.legend(1300, 812, [
    ("box:#e3f4ec:#14724f:", "V: exercised and observed in our runs"),
    ("box:#f0f0ee:#6b6b66:", "D: documented, not measured by us"),
    ("cql", "client request"),
    ("repl", "replica data traffic"),
    ("gossip", "gossip / failure detection"),
], title="Legend", w=286)

s.save(sys.argv[1])
