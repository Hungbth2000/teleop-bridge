
#!/usr/bin/env python3

import argparse
import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV = ROOT / "results/telemetry_robot_tcp.csv"


def load_sessions(path):
    sessions = defaultdict(lambda: defaultdict(dict))

    with path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            if row["role"] != "robot":
                continue

            session_id = row["session_id"]
            timestamp = int(row["timestamp_unix_ms"])
            kind = row["traffic_kind"]

            sessions[session_id][timestamp][kind] = row

    return sessions


def aggregate(samples):
    result = []

    for timestamp, kinds in sorted(samples.items()):
        rows = list(kinds.values())

        budgets = {
            float(row["configured_budget_mbps"])
            for row in rows
        }

        if len(budgets) != 1:
            raise ValueError(
                f"Inconsistent budgets at {timestamp}"
            )

        totals = {
            kind: int(row["tx_bytes_total"])
            for kind, row in kinds.items()
        }

        result.append({
            "timestamp": timestamp,
            "elapsed": max(
                float(row["elapsed_s"])
                for row in rows
            ),
            "budget": budgets.pop(),
            "bytes": sum(totals.values()),
            "video_bytes": totals.get("Video", 0),
            "kinds": kinds,
        })

    return result


def analyze(session_id, samples):
    points = aggregate(samples)

    if len(points) < 2:
        print("Not enough telemetry samples.")
        return

    print(f"\nSession: {session_id}")
    print(f"Duration: {points[-1]['elapsed']:.1f} s")
    print(f"Samples: {len(points)}")

    intervals = []
    mixed_intervals = 0
    counter_resets = 0

    for previous, current in zip(points, points[1:]):
        seconds = (
            current["timestamp"] -
            previous["timestamp"]
        ) / 1000.0

        if seconds <= 0:
            continue

        delta_bytes = (
            current["bytes"] -
            previous["bytes"]
        )

        delta_video = (
            current["video_bytes"] -
            previous["video_bytes"]
        )

        if delta_bytes < 0 or delta_video < 0:
            counter_resets += 1
            continue

        # A sample spanning two different reported
        # phases is not suitable for a single-budget
        # compliance comparison.
        if previous["budget"] != current["budget"]:
            mixed_intervals += 1
            continue

        rate_mbps = (
            delta_bytes * 8 / seconds / 1_000_000
        )

        video_mbps = (
            delta_video * 8 / seconds / 1_000_000
        )

        intervals.append({
            "start": previous["elapsed"],
            "end": current["elapsed"],
            "budget": current["budget"],
            "rate": rate_mbps,
            "video_rate": video_mbps,
            "duration": seconds,
            "bytes": delta_bytes,
        })

    print(f"Usable intervals: {len(intervals)}")
    print(f"Mixed-phase intervals: {mixed_intervals}")
    print(f"Counter-reset intervals: {counter_resets}")

    for budget in sorted({
        item["budget"] for item in intervals
    }):
        phase = [
            item for item in intervals
            if item["budget"] == budget
        ]

        if not phase:
            continue

        total_seconds = sum(
            item["duration"] for item in phase
        )

        total_bytes = sum(
            item["bytes"] for item in phase
        )

        average = (
            total_bytes * 8 /
            total_seconds / 1_000_000
        )

        peak = max(item["rate"] for item in phase)

        over = [
            item for item in phase
            if item["rate"] > budget
        ]

        print(
            f"\n=== Reported {budget:g} Mbit/s phase ==="
        )
        print(f"Intervals:           {len(phase)}")
        print(f"Observed time:       {total_seconds:.1f} s")
        print(f"Average TX:          {average:.3f} Mbit/s")
        print(f"Peak interval TX:    {peak:.3f} Mbit/s")
        print(f"Above-budget intervals: {len(over)}")

        if over:
            for item in over[:10]:
                print(
                    f"  elapsed "
                    f"{item['start']:.1f}-"
                    f"{item['end']:.1f}s: "
                    f"{item['rate']:.3f} Mbit/s"
                )

    print("\n=== Video scheduler counters ===")

    last_video = points[-1]["kinds"].get("Video")

    if last_video is not None:
        for field in (
            "enqueued",
            "sent",
            "dropped",
            "expired",
            "rejected",
            "send_failed",
        ):
            print(
                f"{field:14s}: "
                f"{last_video[field]}"
            )

    print(
        "\nNOTE: Rates are five-second interval "
        "averages, not instantaneous link rates."
    )
    print(
        "An interval may also contain an unobserved "
        "budget transition. This report cannot "
        "prove strict token-bucket compliance."
    )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_CSV,
    )

    parser.add_argument(
        "--session",
        default=None,
    )

    args = parser.parse_args()

    sessions = load_sessions(args.csv)

    if not sessions:
        parser.error("No robot telemetry sessions found")

    if args.session is not None:
        if args.session not in sessions:
            parser.error("Unknown session ID")

        session_id = args.session

    else:
        # Default to the latest session by its
        # first telemetry timestamp.
        session_id = max(
            sessions,
            key=lambda sid: min(sessions[sid]),
        )

    analyze(session_id, sessions[session_id])


if __name__ == "__main__":
    main()
