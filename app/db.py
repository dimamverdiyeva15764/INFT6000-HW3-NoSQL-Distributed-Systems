"""Data-access layer shared by every Python script in the repository.

Public API (frozen, see docs/CONTRACTS.md)::

    from app.db import get_session, stmt, classify_error

    session = get_session()                              # token-aware, no retries, 5 s timeout
    session.execute(stmt("SELECT ... WHERE room = ?", "QUORUM"), ["general"])
    classify_error(exc)                                  # -> 'unavailable', 'write_timeout', ...

Helpers used by the CLI and the workload generator::

    timed_execute(session, statement, params, profile=None, trace=False) -> OpResult
    coordinator_profile("172.28.0.13")                   # execution profile pinned to one coordinator

Driver policies, chosen so that every failure is visible and countable:

* ``TokenAwarePolicy(DCAwareRoundRobinPolicy(local_dc))`` routes each request to a
  replica of the partition (the coordinator is then also a replica).
* ``FallthroughRetryPolicy`` never retries: a timeout or Unavailable reaches the caller.
* No speculative execution (driver default ``NoSpeculativeExecutionPolicy``).
* ``request_timeout`` = ``CLIENT_TIMEOUT_S`` (5 s) - longer than the server-side
  write/read timeouts (2 s / 5 s), so server errors normally arrive first.
"""
import threading
import time
from collections import namedtuple

from cassandra import (ConsistencyLevel, OperationTimedOut, ReadFailure, ReadTimeout,
                       Unavailable, WriteFailure, WriteTimeout)
from cassandra.cluster import EXEC_PROFILE_DEFAULT, Cluster, ExecutionProfile, NoHostAvailable
from cassandra.policies import (DCAwareRoundRobinPolicy, FallthroughRetryPolicy,
                                TokenAwarePolicy, WhiteListRoundRobinPolicy)

from app import config

__all__ = [
    "get_session", "stmt", "classify_error", "cl_value", "cl_name", "timed_execute",
    "coordinator_profile", "OpResult", "OUTCOMES", "shutdown",
]

# Outcome strings written to the 'outcome' column of every results CSV.
OUTCOMES = ("ok", "unavailable", "write_timeout", "read_timeout", "write_failure",
            "read_failure", "no_host", "client_timeout", "other")

_PROFILE_PREFIX = "coord-"
_default_session = None
_stmt_cache = {}
_stmt_lock = threading.Lock()


# --------------------------------------------------------------------------- CL names
def cl_value(name):
    """'QUORUM' -> ConsistencyLevel.QUORUM. Accepts any driver level name, case-insensitive."""
    if isinstance(name, int):
        return name
    key = str(name).strip().upper()
    if key not in ConsistencyLevel.name_to_value:
        valid = ", ".join(sorted(ConsistencyLevel.name_to_value))
        raise ValueError(f"unknown consistency level {name!r}; valid: {valid}")
    return ConsistencyLevel.name_to_value[key]


def cl_name(value):
    """ConsistencyLevel.QUORUM -> 'QUORUM'; strings are normalised to upper case."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip().upper()
    return ConsistencyLevel.value_to_name.get(value, str(value))


# --------------------------------------------------------------------------- sessions
def coordinator_profile(host):
    """Name of the execution profile that sends every request to ``host`` only.

    ``host`` may be an address (172.28.0.13) or a node name (cass3). Profiles exist for
    every host passed to :func:`get_session`.
    """
    return _PROFILE_PREFIX + config.resolve_node(host)


def _base_profile(lbp, timeout):
    return ExecutionProfile(
        load_balancing_policy=lbp,
        retry_policy=FallthroughRetryPolicy(),
        request_timeout=timeout,
    )


def get_session(hosts=None, whitelist=None, keyspace=None, timeout=None):
    """Connect to the cluster and return a Session.

    hosts      contact points (default: ``config.CASSANDRA_HOSTS``).
    whitelist  optional list of addresses/node names; when given, the *default* profile
               uses only these coordinators (used by recovery tooling to read through a
               single, chosen node). Pinned per-host profiles are always available via
               ``execution_profile=coordinator_profile(host)``.
    keyspace   keyspace to ``USE`` (default ``config.KEYSPACE``; pass "" for none).
    timeout    client-side request timeout in seconds (default ``config.CLIENT_TIMEOUT_S``).
    """
    global _default_session
    hosts = [config.resolve_node(h) for h in (hosts or config.CASSANDRA_HOSTS)]
    timeout = config.CLIENT_TIMEOUT_S if timeout is None else timeout
    keyspace = config.KEYSPACE if keyspace is None else keyspace

    if whitelist:
        default_lbp = WhiteListRoundRobinPolicy([config.resolve_node(h) for h in whitelist])
    else:
        default_lbp = TokenAwarePolicy(DCAwareRoundRobinPolicy(local_dc=config.LOCAL_DC))

    profiles = {EXEC_PROFILE_DEFAULT: _base_profile(default_lbp, timeout)}
    for host in hosts:
        profiles[coordinator_profile(host)] = _base_profile(WhiteListRoundRobinPolicy([host]), timeout)

    cluster = Cluster(contact_points=hosts, port=config.CQL_PORT, execution_profiles=profiles)
    session = cluster.connect(keyspace or None)
    _default_session = session
    return session


def shutdown(session):
    """Close the session's cluster connections (safe to call twice)."""
    if session is not None:
        session.cluster.shutdown()


# --------------------------------------------------------------------------- statements
def stmt(cql, cl, serial_cl=None, session=None):
    """Return a cached PreparedStatement for ``cql`` with consistency level ``cl``.

    One PreparedStatement object is kept per (session, cql, cl, serial_cl), so the
    consistency level is fixed on the object and never mutated: threads using different
    levels for the same query cannot interfere. ``session`` defaults to the session most
    recently returned by :func:`get_session`.
    """
    session = session or _default_session
    if session is None:
        raise RuntimeError("stmt() called before get_session()")
    key = (id(session), cql, cl_name(cl), cl_name(serial_cl))
    cached = _stmt_cache.get(key)
    if cached is not None:
        return cached
    with _stmt_lock:
        cached = _stmt_cache.get(key)
        if cached is None:
            cached = session.prepare(cql)
            cached.consistency_level = cl_value(cl)
            if serial_cl:
                cached.serial_consistency_level = cl_value(serial_cl)
            _stmt_cache[key] = cached
    return cached


# --------------------------------------------------------------------------- errors
_ERROR_CLASSES = (
    # Order matters: the specific classes come before any shared base class.
    (Unavailable, "unavailable"),
    (WriteTimeout, "write_timeout"),
    (ReadTimeout, "read_timeout"),
    (WriteFailure, "write_failure"),
    (ReadFailure, "read_failure"),
    (NoHostAvailable, "no_host"),
    (OperationTimedOut, "client_timeout"),
)


def classify_error(exc):
    """Map a driver exception to an outcome string (``None`` -> 'ok').

    unavailable     coordinator knew too few replicas were alive and did not even try
    write_timeout   replicas were tried but too few acknowledged in time (server side)
    read_timeout    same for reads
    write_failure   replicas answered with an error (e.g. disk failure, tombstone overflow)
    read_failure    same for reads
    no_host         the driver had no coordinator it could reach
    client_timeout  the driver's own request_timeout expired before any reply
    other           anything else (syntax error, unexpected exception)
    """
    if exc is None:
        return "ok"
    for cls, label in _ERROR_CLASSES:
        if isinstance(exc, cls):
            return label
    return "other"


# --------------------------------------------------------------------------- timing
OpResult = namedtuple("OpResult", "outcome error_type latency_ms coordinator rows error future")


def _host_address(host):
    if host is None:
        return ""
    address = getattr(host, "address", None)
    if address is None:
        endpoint = getattr(host, "endpoint", None)
        address = getattr(endpoint, "address", None) if endpoint is not None else None
    return str(address if address is not None else host)


def timed_execute(session, statement, params=None, profile=None, trace=False):
    """Execute one statement and never raise driver errors.

    Returns OpResult(outcome, error_type, latency_ms, coordinator, rows, error, future):
    ``rows`` is a list on success (empty for writes), ``error`` the exception otherwise,
    ``coordinator`` the address of the node that coordinated (or was last tried).
    """
    kwargs = {"trace": trace}
    if profile:
        kwargs["execution_profile"] = profile
    t0 = time.perf_counter()
    future = None
    try:
        future = session.execute_async(statement, params, **kwargs)
        rows = list(future.result())
        error = None
    except Exception as exc:  # noqa: BLE001 - every failure is recorded, none is fatal
        rows, error = None, exc
    latency_ms = (time.perf_counter() - t0) * 1000.0
    host = None
    if future is not None:
        host = getattr(future, "coordinator_host", None) or getattr(future, "_current_host", None)
    return OpResult(
        outcome=classify_error(error),
        error_type="" if error is None else type(error).__name__,
        latency_ms=latency_ms,
        coordinator=_host_address(host),
        rows=rows,
        error=error,
        future=future,
    )
