#!/usr/bin/env python3

import csv
import json
from pathlib import Path

BASE = Path("results/task3/real_network")
OUTPUT = BASE / "report"
OUTPUT.mkdir(parents=True, exist_ok=True)

SCENARIOS = {
    "office_lan": {
        "directory": Path("results/final_validation/tcp_udp_office"),
        "runs": {
            "head": "8160d096",
            "left": "8f592fe7",
            "right": "4e449511",
        },
    },
    "inter_city": {
        "directory": Path("results/hybrid_intercity"),
        "runs": {
            "head": "b2232fba",
            "left": "2d282ab5",
            "right": "1b5165ef",
        },
    },
    "warehouse_wifi": {
    "directory": Path("results/warehouse_wifi"),
    "tx_directory": Path("results/quic_warehouse"),
    "runs": {
        "head": "1e5f95aa",
        "left": "20becd4f",
        "right": "f1f0deba",
    },
},
}

STREAMS = {
    "head": ("video_frames_tx.csv", "video_frames_rx.csv"),
    "left": (
        "video_frames_tx_wrist_left.csv",
        "video_frames_rx_wrist_left.csv",
    ),
    "right": (
        "video_frames_tx_wrist_right.csv",
        "video_frames_rx_wrist_right.csv",
    ),
}

def percentile(values, p):
    if not values:
        return None
    values = sorted(values)
    pos = (len(values) - 1) * p / 100
    lo = int(pos)
    hi = min(lo + 1, len(values) - 1)
    return round(values[lo] * (hi - pos) + values[hi] * (pos - lo), 3) if hi != lo else round(values[lo], 3)

def read_run(path, run_id):
    with path.open(newline="") as f:
        return [
            row for row in csv.DictReader(f)
            if row["run_id"] == run_id
        ]

results = {}

for scenario, config in SCENARIOS.items():
    results[scenario] = {}

    for stream, run_id in config["runs"].items():
        tx_file, rx_file = STREAMS[stream]
        directory = config["directory"]

        tx_directory = config.get("tx_directory", directory)

        tx = read_run(tx_directory / tx_file, run_id)
        rx = read_run(directory / rx_file, run_id)

        generated = {
            (r["stream_id"], r["frame_id"]): r
            for r in tx
        }

        received = {
            (r["stream_id"], r["frame_id"]): r
            for r in rx
        }

        good_latencies = []

        for key, tx_row in generated.items():
            rx_row = received.get(key)
            if rx_row is None:
                continue

            latency_ms = (
                int(rx_row["event_ns"])
                - int(tx_row["capture_ns"])
            ) / 1e6

            if 0 <= latency_ms <= 200:
                good_latencies.append(latency_ms)

        total = len(generated)

        result = {
            "run_id": run_id,
            "generated_frames": total,
            "received_frames": len(received),
            "good_frames": len(good_latencies),
            "good_frame_percentage": round(
                100 * len(good_latencies) / total, 3
            ) if total else None,
            "good_latency_p95_ms": percentile(
                good_latencies, 95
            ),
        }

        results[scenario][stream] = result

        print(
            f"{scenario:12} {stream:5} "
            f"good={result['good_frames']}/{total} "
            f"({result['good_frame_percentage']}%) "
            f"p95={result['good_latency_p95_ms']} ms"
        )

(OUTPUT / "video_summary.json").write_text(
    json.dumps(results, indent=2) + "\n"
)

print("\nSaved:", OUTPUT / "video_summary.json")
