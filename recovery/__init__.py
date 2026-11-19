"""Recovery and consensus tooling (Experiments 4 and 6). Owner: Habib Hasanov.

verify_convergence  acknowledged-write log, per-replica freshness reads with tracing,
                    Merkle-tree preview repair parsing, PASS/FAIL convergence verdict
lwt_demo            Paxos lightweight-transaction races, LWT vs. plain write latency,
                    one traced LWT showing the Paxos phases
hints_vs_repair.sh  Exp 4 orchestration: 4a hinted handoff, 4b read repair, 4c anti-entropy
run_exp6.sh         Exp 6 orchestration, including races with one and two nodes down

Modules that talk to Cassandra import ``app.db`` lazily, so the host-side parts (preview
repair through ``docker exec``) run with the Python standard library only, like
``chaos.detect_down``.
"""
