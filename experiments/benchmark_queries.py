#!/usr/bin/env python3

import json
import statistics
import time

import zenoh


QUERY_TOPIC = "teleop/robot/config"
QUERY_COUNT = 20
QUERY_TIMEOUT_MS = 3000


def percentile(values, percentage):
    ordered = sorted(values)

    if not ordered:
        return None

    index = (len(ordered) - 1) * percentage / 100
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = index - lower

    return (
        ordered[lower] * (1 - fraction)
        + ordered[upper] * fraction
    )


def main():
    config = {
        "mode": "client",
        "connect": {
            "endpoints": ["tcp/127.0.0.1:7447"]
        },
        "scouting": {
            "multicast": {"enabled": False}
        },
    }

    latencies_ms = []
    failures = 0
    duplicate_replies = 0

    with zenoh.open(
        zenoh.Config.from_json5(json.dumps(config))
    ) as session:

        for i in range(QUERY_COUNT):
            start = time.monotonic()

            replies = session.get(
                QUERY_TOPIC,
                timeout=QUERY_TIMEOUT_MS,
            )

            successful = []
            first_reply_ms = None

            for reply in replies:
                received_at = time.monotonic()

                if reply.ok is not None:
                    if first_reply_ms is None:
                        first_reply_ms = (
                            received_at - start
                        ) * 1000

                    successful.append(
                        json.loads(
                            reply.ok.payload.to_bytes().decode()
                        )
                    )

            completion_ms = (
                time.monotonic() - start
            ) * 1000

            elapsed_ms = (
                first_reply_ms
                if first_reply_ms is not None
                else completion_ms
            )

            if len(successful) == 1:
                latencies_ms.append(elapsed_ms)
                status = "OK"

            else:
                failures += 1
                status = "FAILED"

                if len(successful) > 1:
                    duplicate_replies += len(successful) - 1

            print(
                f"Query {i + 1:02d}: "
                f"{status}, "
                f"{elapsed_ms:.2f} ms, "
                f"replies={len(successful)}"
            )

            time.sleep(0.1)

    print("\n=== Query Benchmark ===")
    print(f"Total queries: {QUERY_COUNT}")
    print(f"Successes: {len(latencies_ms)}")
    print(f"Failures: {failures}")
    print(f"Extra replies: {duplicate_replies}")

    if latencies_ms:
        print(
            f"Mean latency: "
            f"{statistics.mean(latencies_ms):.2f} ms"
        )
        print(
            f"p50: {percentile(latencies_ms, 50):.2f} ms"
        )
        print(
            f"p95: {percentile(latencies_ms, 95):.2f} ms"
        )
        print(
            f"p99: {percentile(latencies_ms, 99):.2f} ms"
        )


if __name__ == "__main__":
    main()