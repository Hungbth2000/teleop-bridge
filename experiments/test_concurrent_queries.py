#!/usr/bin/env python3

import concurrent.futures
import json
import time

import zenoh


QUERY_TOPIC = "teleop/robot/config"
CONCURRENT_QUERIES = 8
TIMEOUT_MS = 3000


def run_query(session, number):
    start = time.monotonic()

    replies = session.get(
        QUERY_TOPIC,
        timeout=TIMEOUT_MS,
    )

    successful = []
    first_reply_ms = None

    for reply in replies:
        if reply.ok is not None:
            if first_reply_ms is None:
                first_reply_ms = (
                    time.monotonic() - start
                ) * 1000

            data = json.loads(
                reply.ok.payload.to_bytes().decode("utf-8")
            )

            successful.append(data)

    elapsed_ms = (
        first_reply_ms
        if first_reply_ms is not None
        else (time.monotonic() - start) * 1000
    )

    valid = (
        len(successful) == 1
        and successful[0].get("node") == "B3"
    )

    return number, valid, elapsed_ms, len(successful)


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

    with zenoh.open(
        zenoh.Config.from_json5(json.dumps(config))
    ) as session:

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=CONCURRENT_QUERIES
        ) as executor:

            futures = [
                executor.submit(run_query, session, i)
                for i in range(1, CONCURRENT_QUERIES + 1)
            ]

            results = [
                future.result()
                for future in futures
            ]

    successes = 0

    for number, valid, latency, reply_count in sorted(results):
        if valid:
            successes += 1

        print(
            f"Query {number}: "
            f"{'OK' if valid else 'FAILED'}, "
            f"{latency:.2f} ms, "
            f"replies={reply_count}"
        )

    print("\n=== Concurrent Query Test ===")
    print(f"Queries: {CONCURRENT_QUERIES}")
    print(f"Successes: {successes}")
    print(f"Failures: {CONCURRENT_QUERIES - successes}")

    if successes == CONCURRENT_QUERIES:
        print("All queries succeeded; overload was not triggered.")
    else:
        print("Some queries failed; inspect bridge overload logs.")


if __name__ == "__main__":
    main()
