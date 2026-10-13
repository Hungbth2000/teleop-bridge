
#!/usr/bin/env python3

import argparse
import csv
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TX_PATH = ROOT / "results/video_frames_tx.csv"
RX_PATH = ROOT / "results/video_frames_rx.csv"

DEADLINE_MS = 200.0


def read_rows(path):
    if not path.exists():
        raise FileNotFoundError(path)

    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def percentile(values, percent):
    values = sorted(values)

    if not values:
        return None

    position = (len(values) - 1) * percent / 100
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower

    return (
        values[lower] * (1 - fraction)
        + values[upper] * fraction
    )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--run-id",
        help="Run ID printed by the video sender",
    )

    args = parser.parse_args()

    tx_rows = read_rows(TX_PATH)
    rx_rows = read_rows(RX_PATH)

    if not tx_rows:
        raise SystemExit("No TX frame records")

    run_id = args.run_id or tx_rows[-1]["run_id"]

    tx = [
        row for row in tx_rows
        if row["run_id"] == run_id
    ]

    rx = [
        row for row in rx_rows
        if row["run_id"] == run_id
    ]

    if not tx:
        raise SystemExit(
            f"No TX frames for run {run_id}"
        )

    # One generated frame per frame ID.
    generated = {}

    for row in tx:
        key = (
            int(row["stream_id"]),
            int(row["frame_id"]),
        )

        if key in generated:
            raise SystemExit(
                f"Duplicate TX frame key: {key}"
            )

        generated[key] = row

    received = {}
    duplicate_rx = 0

    for row in rx:
        key = (
            int(row["stream_id"]),
            int(row["frame_id"]),
        )

        if key in received:
            duplicate_rx += 1
            continue

        received[key] = row

    on_time = []
    missing = []
    late = []
    unexpected = []

    for key, tx_row in generated.items():
        rx_row = received.get(key)

        if rx_row is None:
            missing.append(key)
            continue

        capture_ns = int(tx_row["capture_ns"])
        arrival_ns = int(rx_row["event_ns"])

        latency_ms = (
            arrival_ns - capture_ns
        ) / 1e6

        if latency_ms < 0:
            unexpected.append(key)
            continue

        if latency_ms <= DEADLINE_MS:
            on_time.append(latency_ms)
        else:
            late.append(latency_ms)

    for key in received:
        if key not in generated:
            unexpected.append(key)

    total = len(generated)
    delivered = len(on_time)

    delivery_pct = 100.0 * delivered / total

    print("\n========== VIDEO FRAME REPORT ==========")
    print(f"Run ID:                {run_id}")
    print(f"Generated frames:      {total}")
    print(f"On-time intact frames: {delivered}")
    print(f"Missing frames:        {len(missing)}")
    print(f"Late frames:           {len(late)}")
    print(f"Unexpected RX records: {len(unexpected)}")
    print(f"Duplicate RX records:  {duplicate_rx}")
    print(f"Deadline:              {DEADLINE_MS:.0f} ms")

    print(
        f"\nOn-time delivery: "
        f"{delivery_pct:.2f}%"
    )

    if on_time:
        print("\nOn-time frame latency:")
        print(
            f"  Mean: "
            f"{statistics.mean(on_time):.3f} ms"
        )
        print(
            f"  p50:  "
            f"{percentile(on_time, 50):.3f} ms"
        )
        print(
            f"  p95:  "
            f"{percentile(on_time, 95):.3f} ms"
        )
        print(
            f"  p99:  "
            f"{percentile(on_time, 99):.3f} ms"
        )
        print(
            f"  Max:  {max(on_time):.3f} ms"
        )

    if (
        delivery_pct >= 80.0
        and not unexpected
        and duplicate_rx == 0
    ):
        print(
            "\nPASS: At least 80% of generated "
            "frames arrived intact within 200 ms."
        )
        return 0

    print(
        "\nFAIL: Delivery target not met, "
        "or telemetry contained unexpected records."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
