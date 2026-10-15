#!/usr/bin/env python3
import json
import re
import statistics
from pathlib import Path

BASE = Path("results/task3/real_network/warehouse_wifi/network_validation")
OFFSET = 1792050232.660134

ping_file = BASE / "warehouse_ping_completed.log"
profile_file = BASE / "warehouse_profile.log"

reply_pattern = re.compile(
    r"\[(\d+\.\d+)\].*icmp_seq=(\d+).*time=([\d.]+) ms"
)
blackout_pattern = re.compile(
    r"Blackout (START|END) monotonic=([\d.]+)"
)
summary_pattern = re.compile(
    r"(\d+) packets transmitted, (\d+) received, "
    r"([\d.]+)% packet loss"
)

replies = []
ping_text = ping_file.read_text()

for line in ping_text.splitlines():
    match = reply_pattern.search(line)
    if match:
        wall, seq, rtt = match.groups()
        replies.append({
            "seq": int(seq),
            "wall_time": float(wall),
            "mono_time": float(wall) - OFFSET,
            "rtt_ms": float(rtt),
        })

summary_match = summary_pattern.search(ping_text)
if not summary_match:
    raise SystemExit("Complete ping summary not found")

sent, received, loss_pct = summary_match.groups()

events = []
start = None

for line in profile_file.read_text().splitlines():
    match = blackout_pattern.search(line)
    if not match:
        continue

    kind, timestamp = match.groups()
    timestamp = float(timestamp)

    if kind == "START":
        start = timestamp
    elif start is not None:
        events.append({
            "start_monotonic_s": start,
            "end_monotonic_s": timestamp,
            "duration_ms": round((timestamp-start)*1000, 3),
            "start_wall_s": round(start + OFFSET, 6),
            "end_wall_s": round(timestamp + OFFSET, 6),
        })
        start = None

valid_rtts = [
    r["rtt_ms"] for r in replies
    if r["rtt_ms"] > 0
]

first = min(r["mono_time"] for r in replies)
last = max(r["mono_time"] for r in replies)

overlapping = [
    e for e in events
    if e["start_monotonic_s"] <= last
    and e["end_monotonic_s"] >= first
]

report = {
    "clock_offset_s": OFFSET,
    "transmitted": int(sent),
    "received": int(received),
    "aggregate_loss_pct": float(loss_pct),
    "raw_reply_records": len(replies),
    "zero_rtt_samples": sum(r["rtt_ms"] == 0 for r in replies),
    "valid_rtt_min_ms": min(valid_rtts),
    "valid_rtt_mean_ms": round(statistics.mean(valid_rtts), 3),
    "valid_rtt_max_ms": max(valid_rtts),
    "first_reply_monotonic_s": round(first, 6),
    "last_reply_monotonic_s": round(last, 6),
    "overlapping_blackouts": overlapping,
    "limitations": [
        "Blackout overlap is based on received reply timestamps.",
        "Lost request send timestamps were not captured.",
        "Aggregate loss includes background and blackout loss.",
        "Background loss cannot be isolated exactly from this trace."
    ]
}

output = BASE / "network_summary.json"
output.write_text(json.dumps(report, indent=2) + "\n")

print(json.dumps(report, indent=2))
print("\nSaved:", output)
