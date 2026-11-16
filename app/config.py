"""Shared constants, read from the environment with the values agreed in docs/CONTRACTS.md."""
import os


def _hosts(value: str) -> list:
    return [h.strip() for h in value.split(",") if h.strip()]


# Static addresses of cass1, cass2, cass3 on the cassnet bridge network.
CASSANDRA_HOSTS = _hosts(os.environ.get("CASSANDRA_HOSTS", "172.28.0.11,172.28.0.12,172.28.0.13"))
KEYSPACE = os.environ.get("KEYSPACE", "chat")
LOCAL_DC = os.environ.get("LOCAL_DC", "dc1")
CLIENT_TIMEOUT_S = float(os.environ.get("CLIENT_TIMEOUT_S", "5"))
CQL_PORT = int(os.environ.get("CQL_PORT", "9042"))

# Friendly names used by the CLI and in printed output.
NODE_NAMES = {
    "172.28.0.11": "cass1",
    "172.28.0.12": "cass2",
    "172.28.0.13": "cass3",
    "172.28.0.14": "cass4",
}
NAME_TO_ADDRESS = {name: addr for addr, name in NODE_NAMES.items()}


def node_name(address) -> str:
    """'172.28.0.12' -> 'cass2'; unknown addresses are returned unchanged."""
    if address is None:
        return ""
    address = str(address).split(":")[0]
    return NODE_NAMES.get(address, address)


def resolve_node(value: str) -> str:
    """Accepts 'cass2' or '172.28.0.12' and returns the IP address."""
    return NAME_TO_ADDRESS.get(value, value)
