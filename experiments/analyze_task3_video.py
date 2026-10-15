#!/usr/bin/env python3
"""Reproduce Task 3 good-frame metrics from packaged evidence."""

import csv
import hashlib
import json
from pathlib import Path

BASE = Path("results/task3/real_network")
EVIDENCE = BASE / "selected_video_runs"
REPORT = BASE / "report"
REPORT.mkdir(parents=True, exist_ok=True)

DEADLINE_MS = 200.0


def read_csv(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def percentile(values, p):
    if not values:
        return None
    values = sorted(values)
    pos = (len(values) - 1) * p / 100
    lo = int(pos)
    hi = min(lo + 1, len(values) - 1)
    frac = pos - lo
    return round(
        values[lo] * (1 - frac) + values[hi] * frac, 3
    )


def frame_key(row):
    return row["stream_id"], row["frame_id"]


def verify_hash(path, expected):
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise RuntimeError(f"Evidence checksum mismatch: {path}")


manifest = json.loads((EVIDENCE / "manifest.json").read_text())
summary = {}

for scenario, cameras in manifest["scenarios"].items():
    summary[scenario] = {}

    for camera, entry in cameras.items():
        tx_file = EVIDENCE / entry["tx_file"]
        rx_file = EVIDENCE / entry["rx_file"]

        verify_hash(tx_file, entry["tx_sha256"])
        verify_hash(rx_file, entry["rx_sha256"])

        tx = read_csv(tx_file)
        rx = read_csv(rx_file)

        if any(r["run_id"] != entry["run_id"] for r in tx + rx):
            raise RuntimeError(f"Unexpected run ID: {scenario}/{camera}")

        tx_keys = [frame_key(r) for r in tx]
        rx_keys = [frame_key(r) for r in rx]

        if len(tx_keys) != len(set(tx_keys)):
            raise RuntimeError("Duplicate TX frame keys")
        if len(rx_keys) != len(set(rx_keys)):
            raise RuntimeError("Duplicate RX frame keys")

        generated = {frame_key(r): r for r in tx}
        received = {frame_key(r): r for r in rx}

        if not set(received).issubset(set(generated)):
            raise RuntimeError("RX contains frames absent from TX")

        good_latencies = []
        late = 0
        invalid = 0

        for key, sent in generated.items():
            arrived = received.get(key)
            if arrived is None:
                continue

            latency = (
                int(arrived["event_ns"]) -
                int(sent["capture_ns"])
            ) / 1e6

            if latency < 0:
                invalid += 1
            elif latency <= DEADLINE_MS:
                good_latencies.append(latency)
            else:
                late += 1

        total = len(generated)
        missing = total - len(received)

        result = {
            "run_id": entry["run_id"],
            "generated": total,
            "received": len(received),
            "good": len(good_latencies),
            "missing": missing,
            "late": late,
            "invalid": invalid,
            "good_percentage": round(
                100 * len(good_latencies) / total, 3
            ) if total else None,
            "good_latency_p95_ms": percentile(
                good_latencies, 95
            ),
        }

        summary[scenario][camera] = result

        print(
            f"{scenario:15} {camera:5} "
            f"good={result['good']}/{total} "
            f"({result['good_percentage']}%) "
            f"p95={result['good_latency_p95_ms']} ms"
        )

output = REPORT / "video_summary.json"
output.write_text(json.dumps(summary, indent=2) + "\n")

print("\nSaved:", output)
