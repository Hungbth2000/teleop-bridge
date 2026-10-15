
#!/usr/bin/env python3

import csv
import statistics
from pathlib import Path

ARCHIVE = Path("results/restart_test/archive")

# Monotonic timestamps captured immediately before
# terminating the old robot bridge.
RESTART_TIMES = {
    1: 101880365087207,
    2: 102369023669559,
    3: 102535983781340,
    4: 102703957405941,
    5: 102861921737119,
}

results = []

for trial, restart_ns in RESTART_TIMES.items():
    path = ARCHIVE / f"video_frames_rx_warehouse_{trial:02d}.csv"

    if not path.exists():
        print(f"Trial {trial}: CSV missing")
        continue

    frames = []

    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            try:
                frames.append({
                    "frame_id": int(row["frame_id"]),
                    "capture_ns": int(row["capture_ns"]),
                    "event_ns": int(row["event_ns"]),
                    "latency_ms": float(row["latency_ms"]),
                })
            except (ValueError, KeyError):
                continue

    before = [
        f for f in frames
        if f["event_ns"] < restart_ns
    ]

    after = [
        f for f in frames
        if f["event_ns"] >= restart_ns
        and f["capture_ns"] >= restart_ns
    ]

    if not before or not after:
        print(f"Trial {trial}: Insufficient frame data")
        continue

    last = max(before, key=lambda f: f["event_ns"])
    first = min(after, key=lambda f: f["event_ns"])

    recovery_ms = (
        first["event_ns"] - restart_ns
    ) / 1_000_000

    interruption_ms = (
        first["event_ns"] - last["event_ns"]
    ) / 1_000_000

    missing_frames = (
        first["frame_id"] - last["frame_id"] - 1
    )

    results.append({
        "trial": trial,
        "recovery_ms": recovery_ms,
        "interruption_ms": interruption_ms,
        "missing_frames": missing_frames,
        "latency_ms": first["latency_ms"],
    })

print("\n========== WAREHOUSE RESTART ANALYSIS ==========")

print(
    f"{'Trial':<7}"
    f"{'Recovery':>12}"
    f"{'Video gap':>12}"
    f"{'Missing':>10}"
    f"{'Latency':>12}"
)

for row in results:
    print(
        f"{row['trial']:<7}"
        f"{row['recovery_ms']:>12.3f}"
        f"{row['interruption_ms']:>12.3f}"
        f"{row['missing_frames']:>10}"
        f"{row['latency_ms']:>12.3f}"
    )

if results:
    recovery = [r["recovery_ms"] for r in results]
    gaps = [r["interruption_ms"] for r in results]

    recovery_passes = sum(x < 1000 for x in recovery)
    gap_passes = sum(x < 1000 for x in gaps)

    print("\nRecovery statistics (ms):")
    print(f"  Mean: {statistics.mean(recovery):.3f}")
    print(f"  Min:  {min(recovery):.3f}")
    print(f"  Max:  {max(recovery):.3f}")

    print("\nVideo interruption statistics (ms):")
    print(f"  Mean: {statistics.mean(gaps):.3f}")
    print(f"  Min:  {min(gaps):.3f}")
    print(f"  Max:  {max(gaps):.3f}")

    print(
        f"\nRestart recovery below 1000 ms: "
        f"{recovery_passes}/{len(results)}"
    )

    print(
        f"Video interruption below 1000 ms: "
        f"{gap_passes}/{len(results)}"
    )
