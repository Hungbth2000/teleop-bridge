
#!/usr/bin/env python3

import argparse
import csv
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"

CAMERAS = {
    "left": 2,
    "right": 3,
}


def read_rows(path):
    if not path.exists():
        return []

    with path.open(
        newline="",
        encoding="utf-8",
    ) as file:
        return list(csv.DictReader(file))


def percentile(values, percentage):
    ordered = sorted(values)

    if not ordered:
        return None

    index = (
        (len(ordered) - 1) *
        percentage / 100
    )

    low = int(index)
    high = min(low + 1, len(ordered) - 1)
    fraction = index - low

    return (
        ordered[low] * (1 - fraction) +
        ordered[high] * fraction
    )


def analyze(camera, stream_id, deadline_ms, run_id=None):
    tx_path = (
        RESULTS /
        f"video_frames_tx_wrist_{camera}.csv"
    )
    rx_path = (
        RESULTS /
        f"video_frames_rx_wrist_{camera}.csv"
    )

    tx_all = read_rows(tx_path)
    rx_all = read_rows(rx_path)

    if not tx_all:
        print(
            f"[{camera}] No sender records: {tx_path}"
        )
        return False

    # Choose the last generated run for this camera,
    # unless the caller supplies a specific run ID.
    if run_id is None:
        run_id = tx_all[-1]["run_id"]

    tx_rows = [
        row for row in tx_all
        if row["run_id"] == run_id
        and int(row["stream_id"]) == stream_id
    ]

    rx_rows = [
        row for row in rx_all
        if row["run_id"] == run_id
        and int(row["stream_id"]) == stream_id
    ]

    tx_by_id = {}
    tx_duplicates = 0

    for row in tx_rows:
        frame_id = int(row["frame_id"])

        if frame_id in tx_by_id:
            tx_duplicates += 1
        else:
            tx_by_id[frame_id] = row

    rx_by_id = {}
    rx_duplicates = 0

    for row in rx_rows:
        frame_id = int(row["frame_id"])

        if frame_id in rx_by_id:
            rx_duplicates += 1
        else:
            rx_by_id[frame_id] = row

    generated_ids = set(tx_by_id)
    received_ids = set(rx_by_id)

    common_ids = generated_ids & received_ids

    # Recompute latency from the event timestamps.
    # This includes the frame's original capture time.
    latencies_by_id = {}

    for frame_id in common_ids:
        tx = tx_by_id[frame_id]
        rx = rx_by_id[frame_id]

        capture_ns = int(tx["capture_ns"])
        completion_ns = int(rx["event_ns"])

        latencies_by_id[frame_id] = (
            completion_ns - capture_ns
        ) / 1_000_000

    on_time = [
        latency
        for latency in latencies_by_id.values()
        if 0 <= latency <= deadline_ms
    ]

    late = sum(
        latency > deadline_ms
        for latency in latencies_by_id.values()
    )

    invalid_timing = sum(
        latency < 0
        for latency in latencies_by_id.values()
    )

    generated = len(generated_ids)
    completed = len(common_ids)
    missing = len(generated_ids - received_ids)
    unexpected = len(received_ids - generated_ids)

    delivery_rate = (
        100 * len(on_time) / generated
        if generated else 0.0
    )

    print(
        f"\n========== {camera.upper()} WRIST =========="
    )
    print(f"Run ID:                {run_id}")
    print(f"Generated frames:      {generated}")
    print(f"Completed frames:      {completed}")
    print(f"On-time intact frames: {len(on_time)}")
    print(f"Missing frames:        {missing}")
    print(f"Late frames:           {late}")
    print(f"Invalid timestamps:    {invalid_timing}")
    print(f"Unexpected RX records: {unexpected}")
    print(f"Duplicate TX records:  {tx_duplicates}")
    print(f"Duplicate RX records:  {rx_duplicates}")
    print(f"Deadline:              {deadline_ms:g} ms")
    print(f"On-time delivery:      {delivery_rate:.2f}%")

    if on_time:
        print("\nOn-time frame latency:")

        print(
            f"  Mean: {statistics.mean(on_time):.3f} ms"
        )

        for p in (50, 95, 99):
            print(
                f"  p{p}:  "
                f"{percentile(on_time, p):.3f} ms"
            )

        print(f"  Max:  {max(on_time):.3f} ms")

    passed = (
        generated > 0
        and delivery_rate >= 80
        and invalid_timing == 0
        and tx_duplicates == 0
        and rx_duplicates == 0
        and unexpected == 0
    )

    print(
        "\nPASS" if passed else "\nFAIL",
        f"— 80% within {deadline_ms:g} ms target",
    )

    return passed


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--camera",
        choices=["left", "right", "both"],
        default="both",
    )

    parser.add_argument(
        "--run-id",
        default=None,
    )

    parser.add_argument(
        "--deadline-ms",
        type=float,
        default=200.0,
    )

    args = parser.parse_args()

    selected = (
        CAMERAS.keys()
        if args.camera == "both"
        else [args.camera]
    )

    results = [
        analyze(
            camera,
            CAMERAS[camera],
            args.deadline_ms,
            args.run_id,
        )
        for camera in selected
    ]

    if not all(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
