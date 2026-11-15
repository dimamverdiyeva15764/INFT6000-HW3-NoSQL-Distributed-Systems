#!/usr/bin/env bash
# End-to-end check: cluster health, schema, replication, cross-coordinator
# read/write, and driver connectivity from the client container.
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"

pass() { echo "PASS  $*"; }

bash scripts/wait_for_cluster.sh 3 60 >/dev/null
pass "3 nodes UN with schema agreement"

keyspace_exists || die "keyspace '$KEYSPACE' missing (run: make schema)"
cql cass1 -e "DESCRIBE KEYSPACE $KEYSPACE" | grep -q "'dc1': '3'" \
  || die "keyspace $KEYSPACE is not replicated with dc1=3"
pass "keyspace $KEYSPACE uses NetworkTopologyStrategy dc1=3"

replicas="$(nt getendpoints "$KEYSPACE" messages smoke | grep -c '^[0-9]')"
[ "$replicas" -eq 3 ] || die "partition 'smoke' has $replicas replicas, expected 3"
pass "partition 'smoke' is stored on 3 replicas"

token="smoke-$(date +%s)-$$"
cql cass1 -e "CONSISTENCY QUORUM;
  INSERT INTO chat.messages (room, msg_id, author, body, writer_run)
  VALUES ('smoke', now(), 'smoke', '$token', 'smoke');" >/dev/null
for node in cass2 cass3; do
  cql "$node" -e "CONSISTENCY QUORUM; SELECT body FROM chat.messages WHERE room = 'smoke';" \
    | grep -q "$token" || die "write via cass1 not visible at QUORUM via $node"
done
pass "QUORUM write via cass1 is readable at QUORUM via cass2 and cass3"

docker compose run --rm -T client python - <<'PY'
import os
import cassandra
from cassandra.cluster import Cluster, ExecutionProfile, EXEC_PROFILE_DEFAULT
from cassandra.policies import DCAwareRoundRobinPolicy, WhiteListRoundRobinPolicy

hosts = os.environ["CASSANDRA_HOSTS"].split(",")
for host in hosts:
    profile = ExecutionProfile(load_balancing_policy=WhiteListRoundRobinPolicy([host]))
    cluster = Cluster([host], execution_profiles={EXEC_PROFILE_DEFAULT: profile})
    session = cluster.connect()
    row = session.execute("SELECT broadcast_address, release_version FROM system.local").one()
    assert str(row.broadcast_address) == host, (host, row.broadcast_address)
    cluster.shutdown()

profile = ExecutionProfile(load_balancing_policy=DCAwareRoundRobinPolicy(local_dc="dc1"))
cluster = Cluster(hosts, execution_profiles={EXEC_PROFILE_DEFAULT: profile})
cluster.connect()
up = sorted(h.address for h in cluster.metadata.all_hosts() if h.is_up)
cluster.shutdown()
assert len(up) == 3, up
print(f"driver {cassandra.__version__}, Cassandra {row.release_version}, hosts up: {', '.join(up)}")
PY
pass "client container reaches every node as coordinator"

if [ -f app/chat.py ]; then
  docker compose run --rm -T client python -m app.chat post \
    --room smoke --author smoke --text "$token-cli" --cl QUORUM >/dev/null
  docker compose run --rm -T client python -m app.chat read --room smoke --limit 5 --cl QUORUM \
    | grep -q "$token-cli" || die "chat CLI could not read back its own message"
  pass "chat CLI post/read at QUORUM"
else
  echo "SKIP  chat CLI check (app/chat.py not in the repository yet)"
fi

cql cass1 -e "CONSISTENCY QUORUM; DELETE FROM chat.messages WHERE room = 'smoke';" >/dev/null
echo "Smoke test passed."
