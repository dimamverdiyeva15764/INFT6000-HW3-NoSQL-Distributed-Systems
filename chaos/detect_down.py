"""Measure Cassandra gossip detection time from a peer's timestamped container logs."""
import argparse
import csv
import queue
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

NODE_IPS = {
    "cass1": "172.28.0.11",
    "cass2": "172.28.0.12",
    "cass3": "172.28.0.13",
}
DOWN_ACTIONS = {"kill", "stop", "partition", "pause"}
UP_ACTIONS = {"start", "heal", "unpause"}
EVENT_FILE = Path("results/logs/chaos_events.csv")
DEFAULT_OUTPUT = Path("results/logs/exp3/failure_detection.csv")
STATE_RE = re.compile(r"is now (DOWN|UP)", re.IGNORECASE)


def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def latest_event(node, transition):
    actions = DOWN_ACTIONS if transition == "down" else UP_ACTIONS
    with EVENT_FILE.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for row in reversed(rows):
        if row.get("node") == node and row.get("action") in actions:
            return row["ts_utc"], row["action"]
    raise ValueError(f"no matching {transition} event for {node} in {EVENT_FILE}")


def matching_detection(line, node, transition):
    match = STATE_RE.search(line)
    if not match or match.group(1).lower() != transition:
        return False
    return NODE_IPS[node] in line or node in line


def tail_logs(observer, since, node, transition, timeout):
    command = ["docker", "logs", "--follow", "--timestamps", "--since", since, observer]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace", bufsize=1)
    lines = queue.Queue()

    def read_lines():
        try:
            for item in process.stdout:
                lines.put(item.rstrip("\r\n"))
        finally:
            lines.put(None)

    reader = threading.Thread(target=read_lines, daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            try:
                line = lines.get(timeout=min(0.5, max(0.01, deadline - time.monotonic())))
            except queue.Empty:
                if process.poll() is not None:
                    raise RuntimeError(f"docker logs exited with status {process.returncode}")
                continue
            if line is None:
                raise RuntimeError(f"docker logs ended before {node} was reported {transition.upper()}")
            if matching_detection(line, node, transition):
                timestamp, _, message = line.partition(" ")
                return timestamp, message
        raise TimeoutError(f"timed out after {timeout}s waiting for {node} {transition.upper()}")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if process.stdout is not None:
            process.stdout.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", choices=NODE_IPS, required=True, help="node whose state changed")
    parser.add_argument("--observer", choices=NODE_IPS, help="peer whose Cassandra logs to follow")
    parser.add_argument("--transition", choices=("down", "up"), required=True)
    parser.add_argument("--since", help="UTC injection timestamp; otherwise use the latest chaos event")
    parser.add_argument("--event-action", help="action label when --since is supplied")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    observer = args.observer or ("cass2" if args.node == "cass1" else "cass1")
    if observer == args.node:
        parser.error("--observer must be a different node from --node")

    try:
        since, action = latest_event(args.node, args.transition) if not args.since else (
            args.since, args.event_action or "")
        detection, message = tail_logs(observer, since, args.node, args.transition, args.timeout)
        detected_at = parse_time(detection)
        injected_at = parse_time(since)
        delta = (detected_at - injected_at).total_seconds()
        if delta < 0:
            raise ValueError(f"detection timestamp precedes injection timestamp: {detection}")

        output = Path(args.output)
        if not output.resolve().is_relative_to(Path("results").resolve()):
            raise ValueError("output must be inside results/")
        output.parent.mkdir(parents=True, exist_ok=True)
        exists = output.exists()
        with output.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            if not exists:
                writer.writerow(("node", "action", "transition", "observer", "injected_utc",
                                 "detected_utc", "detection_seconds", "log_message"))
            writer.writerow((args.node, action, args.transition, observer, since, detection,
                             f"{delta:.3f}", message))
        print(f"{args.node} {args.transition.upper()} detected by {observer} after {delta:.3f}s")
        print(f"saved: {output}")
        return 0
    except (OSError, RuntimeError, TimeoutError, ValueError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
