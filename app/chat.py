"""CassChat - terminal message board on the 3-node Cassandra cluster.

Run inside the client container (it is on the cluster network)::

    docker compose run --rm client python -m app.chat post --room general --author alice --text "hi" --cl QUORUM
    docker compose run --rm client python -m app.chat read --room general --limit 5 --cl ONE
    docker compose run --rm client python -m app.chat --trace read --room general --cl ONE
    docker compose run --rm client python -m app.chat --coordinator cass3 read --room general --cl ALL
    docker compose run --rm client python -m app.chat tail --room general --interval 1 --cl QUORUM
    docker compose run --rm client python -m app.chat hosts

Every command accepts a consistency level (--cl). Failures are printed with their
classified outcome (unavailable, write_timeout, ...) and give exit status 1.
"""
import argparse
import re
import sys
import time
import uuid
from datetime import timedelta

from app import config
from app.db import cl_name, cl_value, coordinator_profile, get_session, shutdown, stmt, timed_execute

INSERT_CQL = ("INSERT INTO messages (room, msg_id, author, body, writer_run) "
              "VALUES (?, ?, ?, ?, ?)")
SELECT_CQL = "SELECT room, msg_id, author, body, WRITETIME(body) AS wt FROM messages WHERE room = ? LIMIT ?"

_REPLICA_RE = re.compile(r"(?:to|from) /?(\d+\.\d+\.\d+\.\d+)")


# --------------------------------------------------------------------------- formatting
def _uuid_time(u):
    """Wall-clock time embedded in a version-1 UUID, as text (UTC)."""
    try:
        from cassandra.util import datetime_from_uuid1
        return datetime_from_uuid1(u).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    except Exception:  # noqa: BLE001 - display only
        return str(u)


def _micros(value):
    if value is None:
        return 0
    if isinstance(value, timedelta):
        return int(value.total_seconds() * 1_000_000)
    return int(value)


def _fail(res, what):
    message = str(res.error).splitlines()[0] if res.error else ""
    print(f"FAILED {what}: outcome={res.outcome} ({res.error_type}) after {res.latency_ms:.1f} ms"
          f" coordinator={config.node_name(res.coordinator) or '-'}")
    if message:
        print(f"  {message[:300]}")


def print_trace(future, out=sys.stdout):
    """Print the server-side query trace and a short interpretation of it."""
    try:
        trace = future.get_query_trace(10)  # positional: ResponseFuture uses max_wait, ResultSet max_wait_sec
    except Exception as exc:  # noqa: BLE001
        print(f"(trace unavailable: {type(exc).__name__}: {exc})", file=out)
        return
    events = list(trace.events or [])
    print(f"\n--- query trace {trace.trace_id} ---", file=out)
    print(f"request:     {trace.request_type}", file=out)
    print(f"coordinator: {config.node_name(trace.coordinator)} ({trace.coordinator})", file=out)
    print(f"duration:    {_micros(trace.duration)} us", file=out)
    print(f"{'elapsed_us':>10}  {'node':<6}  activity", file=out)
    nodes = {str(trace.coordinator)}
    flags = {"digest_mismatch": False, "read_repair": False, "speculative_retry": False}
    for ev in events:
        source = str(ev.source)
        nodes.add(source)
        desc = " ".join(str(ev.description).split())
        for addr in _REPLICA_RE.findall(desc):
            nodes.add(addr)
        low = desc.lower()
        flags["digest_mismatch"] |= "digest mismatch" in low or "mismatch" in low
        flags["read_repair"] |= "repair" in low
        flags["speculative_retry"] |= "speculat" in low
        print(f"{_micros(ev.source_elapsed):>10}  {config.node_name(source):<6}  {desc[:150]}", file=out)
    print("--- summary ---", file=out)
    print("nodes involved:      " + ", ".join(sorted(config.node_name(n) for n in nodes)), file=out)
    print(f"digest mismatch:     {'yes' if flags['digest_mismatch'] else 'no'}", file=out)
    print(f"read repair:         {'yes' if flags['read_repair'] else 'no'}", file=out)
    print(f"speculative retry:   {'yes' if flags['speculative_retry'] else 'no'}", file=out)


# --------------------------------------------------------------------------- commands
def cmd_post(session, args, profile):
    msg_id = uuid.uuid1()
    run = args.run or "cli"
    res = timed_execute(session, stmt(INSERT_CQL, args.cl, session=session), [args.room, msg_id, args.author, args.text, run],
                        profile=profile, trace=args.trace)
    if res.outcome != "ok":
        _fail(res, f"post at {cl_name(args.cl)}")
        return 1
    print(f"posted room={args.room} msg_id={msg_id} cl={cl_name(args.cl)} "
          f"latency={res.latency_ms:.2f} ms coordinator={config.node_name(res.coordinator)}")
    if args.trace:
        print_trace(res.future)
    return 0


def _read(session, args, profile, trace=False):
    return timed_execute(session, stmt(SELECT_CQL, args.cl, session=session), [args.room, args.limit],
                         profile=profile, trace=trace)


def _print_row(r):
    print(f"  {_uuid_time(r.msg_id)}  {r.author:<12} {r.body}")


def cmd_read(session, args, profile):
    res = _read(session, args, profile, trace=args.trace)
    if res.outcome != "ok":
        _fail(res, f"read at {cl_name(args.cl)}")
        return 1
    print(f"room={args.room} cl={cl_name(args.cl)} rows={len(res.rows)} "
          f"latency={res.latency_ms:.2f} ms coordinator={config.node_name(res.coordinator)}")
    for r in res.rows:
        _print_row(r)
    if args.trace:
        print_trace(res.future)
    return 0


def cmd_tail(session, args, profile):
    seen = set()
    first = True
    print(f"tailing room={args.room} at {cl_name(args.cl)} every {args.interval}s (Ctrl-C to stop)")
    try:
        while True:
            res = _read(session, args, profile)
            now = time.strftime("%H:%M:%S", time.gmtime())
            if res.outcome != "ok":
                print(f"[{now}Z] read FAILED outcome={res.outcome} ({res.error_type}) "
                      f"{res.latency_ms:.0f} ms", flush=True)
            else:
                new = [r for r in reversed(res.rows) if r.msg_id not in seen]
                for r in new:
                    seen.add(r.msg_id)
                    if not first:
                        _print_row(r)
                if first:
                    for r in new[-args.limit:]:
                        _print_row(r)
                    first = False
                sys.stdout.flush()
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print()
    return 0


def cmd_hosts(session, args, profile):
    """Driver's view of the cluster: which nodes it currently considers up."""
    meta = session.cluster.metadata
    print(f"cluster: {meta.cluster_name}")
    for h in sorted(meta.all_hosts(), key=lambda h: str(h.address)):
        state = "UP" if h.is_up else "DOWN"
        print(f"  {config.node_name(h.address):<6} {h.address:<15} {h.datacenter}/{h.rack}  "
              f"{h.release_version or '':<8} {state}")
    return 0


# --------------------------------------------------------------------------- CLI
def _cl_arg(value):
    try:
        cl_value(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None  # validates
    return value.upper()


def build_parser():
    p = argparse.ArgumentParser(prog="python -m app.chat", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--trace", action="store_true",
                   help="print the server-side query trace (coordinator, replicas, read repair)")
    p.add_argument("--coordinator", metavar="NODE",
                   help="send the request to this node only (cass1/cass2/cass3 or an IP)")
    p.add_argument("--hosts", help="comma-separated contact points (default: $CASSANDRA_HOSTS)")
    p.add_argument("--timeout", type=float, default=None, help="client timeout in seconds (default 5)")
    sub = p.add_subparsers(dest="command", required=True)

    post = sub.add_parser("post", help="post one message")
    post.add_argument("--room", required=True)
    post.add_argument("--author", required=True)
    post.add_argument("--text", required=True)
    post.add_argument("--cl", type=_cl_arg, default="QUORUM", help="consistency level (default QUORUM)")
    post.add_argument("--run", help="value stored in writer_run (default 'cli')")
    post.set_defaults(func=cmd_post)

    read = sub.add_parser("read", help="read the newest messages of a room")
    read.add_argument("--room", required=True)
    read.add_argument("--limit", type=int, default=10)
    read.add_argument("--cl", type=_cl_arg, default="QUORUM", help="consistency level (default QUORUM)")
    read.set_defaults(func=cmd_read)

    tail = sub.add_parser("tail", help="poll a room and print new messages")
    tail.add_argument("--room", required=True)
    tail.add_argument("--interval", type=float, default=1.0)
    tail.add_argument("--limit", type=int, default=10)
    tail.add_argument("--cl", type=_cl_arg, default="QUORUM", help="consistency level (default QUORUM)")
    tail.set_defaults(func=cmd_tail)

    hosts = sub.add_parser("hosts", help="show which nodes the driver sees as up")
    hosts.set_defaults(func=cmd_hosts)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    hosts = [config.resolve_node(h) for h in (args.hosts.split(",") if args.hosts else config.CASSANDRA_HOSTS)]
    if args.coordinator and config.resolve_node(args.coordinator) not in hosts:
        hosts.append(config.resolve_node(args.coordinator))
    try:
        session = get_session(hosts=hosts, timeout=args.timeout)
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED to connect: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("Run inside the client container: docker compose run --rm client python -m app.chat ...",
              file=sys.stderr)
        return 2
    profile = coordinator_profile(args.coordinator) if args.coordinator else None
    try:
        return args.func(session, args, profile)
    finally:
        shutdown(session)


if __name__ == "__main__":
    sys.exit(main())
