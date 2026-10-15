#!/usr/bin/env python3

import csv
import json
from pathlib import Path

BASE = Path("results/task2/recovery_tcp_udp")
REPORT = BASE / "report"
REPORT.mkdir(parents=True, exist_ok=True)

roles = ("operator", "robot")
results = {}

for role in roles:
    path = BASE / f"{role}_bridge_restart/recovery_summary.json"
    results[role] = json.loads(path.read_text())

fields = [
    "role",
    "downtime_ms",
    "head_ms",
    "left_ms",
    "right_ms",
    "motion_ms",
    "full_recovery_ms",
    "all_paths_recovered",
]

rows = []

for role in roles:
    data = results[role]

    rows.append({
        "role": role,
        "downtime_ms": data["bridge_downtime_ms"],
        "head_ms": data["video"]["head"]["recovery_after_launch_ms"],
        "left_ms": data["video"]["left"]["recovery_after_launch_ms"],
        "right_ms": data["video"]["right"]["recovery_after_launch_ms"],
        "motion_ms": data["motion"]["recovery_after_launch_ms"],
        "full_recovery_ms": data["full_recovery_after_launch_ms"],
        "all_paths_recovered": data["all_paths_recovered"],
    })

with (REPORT / "recovery_summary.csv").open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)

summary = {
    "transport": "hybrid TCP/UDP",
    "restart_type": "SIGKILL followed by process relaunch",
    "planned_offline_seconds": 5,
    "operator": rows[0],
    "robot": rows[1],
    "both_sides_recovered": all(
        row["all_paths_recovered"] for row in rows
    ),
}

(REPORT / "summary.json").write_text(
    json.dumps(summary, indent=2) + "\n"
)

lines = [
    "# Task 2.5 — Bridge Restart Recovery",
    "",
    "The operator and robot bridges were tested separately.",
    "Each bridge was killed with SIGKILL, kept offline for",
    "approximately five seconds, then relaunched.",
    "",
    "| Metric | Operator | Robot |",
    "|---|---:|---:|",
]

labels = [
    ("Downtime", "downtime_ms"),
    ("Head video recovery", "head_ms"),
    ("Left wrist recovery", "left_ms"),
    ("Right wrist recovery", "right_ms"),
    ("Fresh motion recovery", "motion_ms"),
    ("Full recovery", "full_recovery_ms"),
]

for label, key in labels:
    lines.append(
        f"| {label} | {rows[0][key]:.3f} ms | "
        f"{rows[1][key]:.3f} ms |"
    )

lines += [
    "",
    "Both trials recovered all three decoded video streams",
    "and the fresh, applied motion-command path.",
    "",
    "Recovery is measured from replacement-process launch.",
    "The deliberate five-second downtime is reported separately.",
    "",
    "A good frame is successfully decoded, captured after",
    "restart, and has capture-to-decode latency <= 200 ms.",
    "A recovered motion command is created after restart,",
    "is fresh (age 0–150 ms), and is applied at B3.",
    "",
    "This validates the two observed restart trials, not a",
    "statistical worst-case recovery bound.",
    "",
    "Evidence:",
    "- operator_bridge_restart/recovery_summary.json",
    "- robot_bridge_restart/recovery_summary.json",
    "- Each trial's restart_events.json, decoded-frame CSVs,",
    "  motion_rx.csv, bridge.log, and runner.log",
]

(REPORT / "report.md").write_text("\n".join(lines) + "\n")

print(json.dumps(summary, indent=2))
print("\nRESULT:", "PASS" if summary["both_sides_recovered"] else "INCOMPLETE")
