#!/usr/bin/env python3
"""Preserve selected Task 3 video runs as standalone evidence."""

import csv
import hashlib
import json
from pathlib import Path

ROOT = Path("results/task3/real_network")
DEST = ROOT / "selected_video_runs"

SCENARIOS = {
    "office_lan": {
        "source": Path("results/final_validation/tcp_udp_office"),
        "runs": {
            "head": "8160d096",
            "left": "8f592fe7",
            "right": "4e449511",
        },
    },
    "inter_city": {
        "source": Path("results/hybrid_intercity"),
        "runs": {
            "head": "b2232fba",
            "left": "2d282ab5",
            "right": "1b5165ef",
        },
    },
    "warehouse_wifi": {
        "source": ROOT / "warehouse_wifi/retest_02/application",
        "runs": {
            "head": "bc0912d0",
            "left": "33b58e23",
            "right": "fccdda22",
        },
    },
}

FILES = {
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


def select_rows(source, run_id):
    with source.open(newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        rows = [row for row in reader if row["run_id"] == run_id]
    if not fields or not rows:
        raise RuntimeError(f"No run {run_id} in {source}")
    return fields, rows


def frame_keys(rows):
    return [
        (row["stream_id"], row["frame_id"])
        for row in rows
    ]


def write_csv(destination, fields, rows):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fields,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


manifest = {"scenarios": {}}

for scenario, config in SCENARIOS.items():
    manifest["scenarios"][scenario] = {}

    for camera, run_id in config["runs"].items():
        tx_name, rx_name = FILES[camera]
        source = config["source"]

        tx_fields, tx = select_rows(source / tx_name, run_id)
        rx_fields, rx = select_rows(source / rx_name, run_id)

        tx_keys = frame_keys(tx)
        rx_keys = frame_keys(rx)

        if len(tx_keys) != len(set(tx_keys)):
            raise RuntimeError(f"Duplicate TX frames: {scenario}/{camera}")

        if len(rx_keys) != len(set(rx_keys)):
            raise RuntimeError(f"Duplicate RX frames: {scenario}/{camera}")

        if not set(rx_keys).issubset(set(tx_keys)):
            raise RuntimeError(f"Unmatched RX frames: {scenario}/{camera}")

        directory = DEST / scenario / camera
        tx_output = directory / "tx.csv"
        rx_output = directory / "rx.csv"

        write_csv(tx_output, tx_fields, tx)
        write_csv(rx_output, rx_fields, rx)

        manifest["scenarios"][scenario][camera] = {
            "run_id": run_id,
            "source_tx": str(source / tx_name),
            "source_rx": str(source / rx_name),
            "tx_file": str(tx_output.relative_to(DEST)),
            "rx_file": str(rx_output.relative_to(DEST)),
            "generated_frames": len(tx),
            "received_frames": len(rx),
            "tx_sha256": hashlib.sha256(
                tx_output.read_bytes()
            ).hexdigest(),
            "rx_sha256": hashlib.sha256(
                rx_output.read_bytes()
            ).hexdigest(),
        }

        print(
            f"{scenario:15} {camera:5} "
            f"TX={len(tx)} RX={len(rx)} run={run_id}"
        )

manifest_path = DEST / "manifest.json"
manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
print("\nSaved:", manifest_path)
