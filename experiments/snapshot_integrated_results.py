
#!/usr/bin/env python3

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESULTS = ROOT / "results"
DEST = RESULTS / "final_validation" / "integrated_01"

DEST.mkdir(parents=True, exist_ok=True)

# IDs from the successful integrated run.
RUNS = {
    "head": "766815dc",
    "left": "37d64914",
    "right": "977825f0",
}

CONTROL_EXPERIMENTS = {
    "normal_1791931644425546670",
    "degraded_1791931657294461280",
}


def extract_rows(source, destination, field, values):
    if not source.exists():
        raise FileNotFoundError(source)

    with source.open(
        newline="",
        encoding="utf-8",
    ) as file:
        reader = csv.DictReader(file)
        fields = reader.fieldnames

        if not fields or field not in fields:
            raise ValueError(
                f"Missing field {field} in {source}"
            )

        rows = [
            row for row in reader
            if row[field] in values
        ]

    with destination.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fields,
        )
        writer.writeheader()
        writer.writerows(rows)

    print(
        f"[SNAPSHOT] {destination.name}: "
        f"{len(rows)} rows"
    )

    return len(rows)


frame_files = {
    "head": (
        "video_frames_tx.csv",
        "video_frames_rx.csv",
    ),
    "left": (
        "video_frames_tx_wrist_left.csv",
        "video_frames_rx_wrist_left.csv",
    ),
    "right": (
        "video_frames_tx_wrist_right.csv",
        "video_frames_rx_wrist_right.csv",
    ),
}

counts = {}

for camera, filenames in frame_files.items():
    run_id = RUNS[camera]

    for direction, filename in zip(
        ("tx", "rx"),
        filenames,
    ):
        count = extract_rows(
            RESULTS / filename,
            DEST / filename,
            "run_id",
            {run_id},
        )

        counts[f"{camera}_{direction}"] = count


control_count = extract_rows(
    RESULTS / "control_latency_trials.csv",
    DEST / "control_latency_trials.csv",
    "experiment_id",
    CONTROL_EXPERIMENTS,
)

manifest = {
    "description": (
        "Three adaptive cameras with "
        "normal/degraded E-stop trials"
    ),
    "video_run_ids": RUNS,
    "control_experiment_ids": sorted(
        CONTROL_EXPERIMENTS
    ),
    "frame_record_counts": counts,
    "control_records": control_count,
    "deadline_ms": 200,
    "budget_normal_bps": 8_000_000,
    "budget_degraded_bps": 2_000_000,
    "validated_transport": (
        "local WSL2 Zenoh/C++ TCP bridge"
    ),
}

with (DEST / "manifest.json").open(
    "w",
    encoding="utf-8",
) as file:
    json.dump(
        manifest,
        file,
        indent=2,
    )

print("\n[SNAPSHOT] Completed")
print(f"[SNAPSHOT] Directory: {DEST}")
