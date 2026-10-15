#!/usr/bin/env python3

import csv
import json
import statistics
from collections import Counter
from pathlib import Path

BASE = Path("results/task2/request_reply_tcp_udp")
SOURCE = BASE / "evidence/query_workload.csv"
REPORT = BASE / "report"

REPORT.mkdir(parents=True, exist_ok=True)


def percentile(values, percentage):
    values = sorted(values)
    if not values:
        return None

    index = (len(values) - 1) * percentage / 100
    low = int(index)
    high = min(low + 1, len(values) - 1)
    fraction = index - low

    return (
        values[low] * (1 - fraction)
        + values[high] * fraction
    )


with SOURCE.open(newline="") as f:
    rows = list(csv.DictReader(f))

successful = [
    r for r in rows
    if r["status"] == "OK" and int(r["reply_count"]) == 1
]

latencies = [
    float(r["first_reply_ms"])
    for r in successful
    if r["first_reply_ms"]
]

zero_reply = [
    r for r in rows
    if int(r["reply_count"]) == 0
]

duplicate_reply = [
    r for r in rows
    if int(r["reply_count"]) > 1
]

extra_replies = sum(
    max(0, int(r["reply_count"]) - 1)
    for r in rows
)

summary = {
    "queries_sent": len(rows),
    "successful_queries": len(successful),
    "failed_queries": len(rows) - len(successful),
    "zero_reply_queries": len(zero_reply),
    "duplicate_reply_queries": len(duplicate_reply),
    "extra_replies": extra_replies,
    "success_rate_pct": (
        100 * len(successful) / len(rows)
        if rows else 0
    ),
    "first_reply_latency_ms": {
        "mean": statistics.mean(latencies) if latencies else None,
        "p50": percentile(latencies, 50),
        "p95": percentile(latencies, 95),
        "p99": percentile(latencies, 99),
        "max": max(latencies) if latencies else None,
    },
}

summary["normal_workload_pass"] = (
    len(rows) > 0
    and len(successful) == len(rows)
    and extra_replies == 0
)

(REPORT / "summary.json").write_text(
    json.dumps(summary, indent=2) + "\n"
)

print(json.dumps(summary, indent=2))
print(
    "\nRESULT:",
    "PASS" if summary["normal_workload_pass"] else "FAIL"
)
