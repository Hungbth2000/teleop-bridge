#!/usr/bin/env python3

import argparse
import csv
import json
import time
from pathlib import Path

import zenoh


QUERY_TOPIC = "teleop/robot/config"


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--duration",
        type=float,
        default=75.0,
    )

    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
    )

    parser.add_argument(
        "--output",
        default="results/query_workload.csv",
    )

    args = parser.parse_args()

    if args.duration <= 0 or args.interval <= 0:
        parser.error("Duration and interval must be positive")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    config = {
        "mode": "client",
        "connect": {
            "endpoints": ["tcp/127.0.0.1:7447"]
        },
        "scouting": {
            "multicast": {"enabled": False}
        },
    }

    successes = 0
    failures = 0
    duplicates = 0
    query_number = 0

    with (
        output.open("w", newline="") as file,
        zenoh.open(
            zenoh.Config.from_json5(json.dumps(config))
        ) as session,
    ):
        writer = csv.writer(file)

        writer.writerow([
            "query_number",
            "start_monotonic_ns",
            "status",
            "first_reply_ms",
            "completion_ms",
            "reply_count",
        ])

        experiment_start = time.monotonic()
        next_query_at = experiment_start
        deadline = experiment_start + args.duration

        while time.monotonic() < deadline:
            remaining = next_query_at - time.monotonic()

            if remaining > 0:
                time.sleep(remaining)

            if time.monotonic() >= deadline:
                break

            query_number += 1

            start_ns = time.monotonic_ns()
            start = time.monotonic()

            replies = session.get(
                QUERY_TOPIC,
                timeout=3000,
            )

            reply_count = 0
            first_reply_ms = None

            for reply in replies:
                if reply.ok is None:
                    continue

                try:
                    data = json.loads(
                        reply.ok.payload.to_bytes().decode("utf-8")
                    )

                    if data.get("node") != "B3":
                        continue

                    reply_count += 1

                    if first_reply_ms is None:
                        first_reply_ms = (
                            time.monotonic() - start
                        ) * 1000

                except (ValueError, UnicodeDecodeError):
                    continue

            completion_ms = (
                time.monotonic() - start
            ) * 1000

            if reply_count == 1:
                status = "OK"
                successes += 1
            else:
                status = "FAILED"
                failures += 1

            duplicates += max(0, reply_count - 1)

            writer.writerow([
                query_number,
                start_ns,
                status,
                (
                    f"{first_reply_ms:.3f}"
                    if first_reply_ms is not None
                    else ""
                ),
                f"{completion_ms:.3f}",
                reply_count,
            ])

            file.flush()

            print(
                f"[A3] Query {query_number}: "
                f"{status}, replies={reply_count}, "
                f"first_reply_ms={first_reply_ms}",
                flush=True,
            )

            next_query_at += args.interval

            # Skip missed slots instead of issuing a burst.
            while next_query_at <= time.monotonic():
                next_query_at += args.interval

    print(
        f"[A3] Finished: total={query_number}, "
        f"successes={successes}, "
        f"failures={failures}, "
        f"extra_replies={duplicates}",
        flush=True,
    )

    print(f"[A3] CSV: {output}", flush=True)


if __name__ == "__main__":
    main()
