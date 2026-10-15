#!/usr/bin/env python3

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

BASE = Path("results/task2/reliable_commands_tcp_udp")
EVIDENCE = BASE / "evidence"
REPORT = BASE / "report"
REPORT.mkdir(parents=True, exist_ok=True)


def load(name):
    with (EVIDENCE / name).open(newline="") as f:
        return list(csv.DictReader(f))


a1 = load("a1_reliable_events.csv")
b3 = load("b3_reliable_events.csv")

sends = [r for r in a1 if r["event"] == "SENT"]
applications = [r for r in b3 if r["event"] == "APPLIED"]
confirmations = [r for r in a1 if r["event"] == "CONFIRMED"]

# Retries share the same ID. Count unique commands, not send attempts.
sent_by_id = {}
for row in sends:
    sent_by_id.setdefault(row["command_id"], row)

applied_by_id = defaultdict(list)
for row in applications:
    applied_by_id[row["command_id"]].append(row)

confirmed_ids = {r["command_id"] for r in confirmations}

sent_ids = set(sent_by_id)
applied_ids = set(applied_by_id)

lost_ids = sorted(sent_ids - applied_ids)
unconfirmed_ids = sorted(sent_ids - confirmed_ids)
duplicate_ids = {
    cid: len(rows)
    for cid, rows in applied_by_id.items()
    if len(rows) > 1
}

# Compare actual event chronology, not just numeric command IDs.
sent_order = [
    cid for cid, row in sorted(
        sent_by_id.items(),
        key=lambda item: int(item[1]["monotonic_ns"])
    )
]

applied_order = [
    row["command_id"]
    for row in sorted(
        applications,
        key=lambda row: int(row["monotonic_ns"])
    )
]

ordered = sent_order == applied_order

rows = []
late_estops = []

for cid in sent_order:
    sent = sent_by_id[cid]
    matches = applied_by_id.get(cid, [])

    created_ns = int(sent["created_ns"])
    opcode = sent["opcode"]

    if matches:
        applied = matches[0]
        effect_ns = int(applied["effect_ns"])
        latency_ms = (effect_ns - created_ns) / 1e6
        status = applied["status"]
    else:
        effect_ns = None
        latency_ms = None
        status = "MISSING"

    if opcode == "ESTOP" and (
        latency_ms is None
        or latency_ms < 0
        or latency_ms > 200
    ):
        late_estops.append(cid)

    rows.append({
        "command_id": cid,
        "opcode": opcode,
        "created_ns": created_ns,
        "effect_ns": effect_ns if effect_ns is not None else "",
        "effect_latency_ms": (
            round(latency_ms, 6)
            if latency_ms is not None else ""
        ),
        "application_count": len(matches),
        "confirmed": cid in confirmed_ids,
        "status": status,
    })

with (REPORT / "command_results.csv").open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)

estop_latencies = [
    r["effect_latency_ms"]
    for r in rows
    if r["opcode"] == "ESTOP"
    and isinstance(r["effect_latency_ms"], (int, float))
]

expected_alternation = [
    "ESTOP" if i % 2 == 0 else "RESET"
    for i in range(len(rows))
]
actual_alternation = [r["opcode"] for r in rows]

passed = (
    len(sent_ids) == 22
    and len(applications) == 22
    and len(estop_latencies) == 11
    and not lost_ids
    and not unconfirmed_ids
    and not duplicate_ids
    and not late_estops
    and ordered
    and actual_alternation == expected_alternation
    and all(r["status"] == "APPLIED" for r in rows)
)

summary = {
    "unique_commands_sent": len(sent_ids),
    "applications": len(applications),
    "confirmed": len(sent_ids - set(unconfirmed_ids)),
    "lost_command_ids": lost_ids,
    "unconfirmed_command_ids": unconfirmed_ids,
    "duplicate_application_counts": duplicate_ids,
    "application_order_matches_send_order": ordered,
    "alternating_estop_reset": actual_alternation == expected_alternation,
    "estops_applied": len(estop_latencies),
    "estops_over_200ms": late_estops,
    "max_estop_effect_latency_ms": (
        max(estop_latencies) if estop_latencies else None
    ),
    "normal_workload_pass": passed,
}

(REPORT / "summary.json").write_text(
    json.dumps(summary, indent=2) + "\n"
)

print(json.dumps(summary, indent=2))
print("\nRESULT:", "PASS" if passed else "FAIL")
print("Per-command proof:", REPORT / "command_results.csv")
print("Summary:", REPORT / "summary.json")
