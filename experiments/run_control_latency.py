
#!/usr/bin/env python3

import argparse
import csv
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
A1_SCRIPT = ROOT / "mock/operator/a1_reliable.py"
A1_EVENTS = ROOT / "results/control_events_a1.csv"
OUTPUT = ROOT / "results/control_latency_trials.csv"

FIELDS = [
    "experiment_id",
    "phase",
    "trial",
    "command",
    "command_id",
    "started_unix_ns",
    "outcome",
    "ack_status",
    "attempts",
    "created_ns",
    "effect_ns",
    "ack_received_ns",
    "effect_latency_ms",
    "confirmation_latency_ms",
    "error",
]


def percentile(values, percent):
    """Linear-interpolated percentile."""
    values = sorted(values)

    if not values:
        return None

    position = (len(values) - 1) * percent / 100.0
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower

    return (
        values[lower] * (1 - fraction)
        + values[upper] * fraction
    )


def read_command_events(command_id):
    """Return A1 events belonging to one exact command ID."""
    if not A1_EVENTS.exists():
        return []

    with A1_EVENTS.open(newline="") as f:
        return [
            row
            for row in csv.DictReader(f)
            if row["command_id"] == str(command_id)
        ]


def new_command_id():
    # Matches the signed 64-bit SQLite ID requirement.
    return time.time_ns()


def execute_command(
    command,
    phase,
    trial,
    experiment_id,
    timeout_ms,
    retries,
):
    command_id = new_command_id()
    started_ns = time.time_ns()

    result = {
        "experiment_id": experiment_id,
        "phase": phase,
        "trial": trial,
        "command": command.upper(),
        "command_id": command_id,
        "started_unix_ns": started_ns,
        "outcome": "FAILED",
        "ack_status": "",
        "attempts": 0,
        "created_ns": "",
        "effect_ns": "",
        "ack_received_ns": "",
        "effect_latency_ms": "",
        "confirmation_latency_ms": "",
        "error": "",
    }

    args = [
        sys.executable,
        str(A1_SCRIPT),
        "--command", command,
        "--id", str(command_id),
        "--timeout-ms", str(timeout_ms),
        "--retries", str(retries),
    ]

    # Each A1 invocation is a new process, so its
    # asynchronous CSV writer closes on exit.
    try:
        completed = subprocess.run(
            args,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )

    except subprocess.TimeoutExpired:
        result["error"] = "A1_PROCESS_TIMEOUT"
        return result

    if completed.returncode != 0:
        result["error"] = (
            f"A1_EXIT_{completed.returncode}: "
            + completed.stderr.strip()[:300]
        )
        return result

    events = read_command_events(command_id)

    sent = [
        row for row in events
        if row["event"] == "SENT"
    ]

    received = [
        row for row in events
        if row["event"] == "ACK_RECEIVED"
    ]

    result["attempts"] = len(sent)

    if not sent:
        result["error"] = "NO_SENT_EVENT"
        return result

    created_ns = int(sent[0]["created_ns"])
    result["created_ns"] = created_ns

    if not received:
        result["error"] = "NO_ACK_RECEIVED"
        return result

    # A1 preserves the first matching ACK.
    first_ack = received[0]

    status = first_ack["status"]
    effect_text = first_ack["effect_ns"]

    ack_ns = int(first_ack["monotonic_ns"])

    result["ack_status"] = status
    result["ack_received_ns"] = ack_ns

    result["confirmation_latency_ms"] = round(
        (ack_ns - created_ns) / 1e6, 3
    )

    if effect_text:
        effect_ns = int(effect_text)
        result["effect_ns"] = effect_ns

        if effect_ns > 0:
            result["effect_latency_ms"] = round(
                (effect_ns - created_ns) / 1e6, 3
            )

    if status not in ("APPLIED", "DUPLICATE"):
        result["error"] = f"ACK_STATUS_{status}"
        return result

    if not result["effect_latency_ms"]:
        result["error"] = "MISSING_EFFECT_TIMESTAMP"
        return result

    if result["effect_latency_ms"] < 0:
        result["error"] = "INVALID_EFFECT_TIMESTAMP"
        return result

    # Normal trials use unique IDs and expect a newly
    # applied command. ACK-loss trials can legitimately
    # return DUPLICATE after B3 suppresses the first ACK.
    if phase != "ack_loss" and status != "APPLIED":
        result["error"] = "UNEXPECTED_DUPLICATE"
        return result

    result["outcome"] = "CONFIRMED"
    return result


def append_result(row):
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    write_header = (
        not OUTPUT.exists()
        or OUTPUT.stat().st_size == 0
    )

    with OUTPUT.open("a", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=FIELDS,
        )

        if write_header:
            writer.writeheader()

        writer.writerow(row)


def print_summary(results):
    estops = [
        r for r in results
        if r["command"] == "ESTOP"
    ]

    confirmed = [
        r for r in estops
        if r["outcome"] == "CONFIRMED"
    ]

    effects = [
        float(r["effect_latency_ms"])
        for r in confirmed
    ]

    confirmations = [
        float(r["confirmation_latency_ms"])
        for r in confirmed
    ]

    print("\n========== EXPERIMENT SUMMARY ==========")
    print(f"E-stop trials:       {len(estops)}")
    print(f"Confirmed:           {len(confirmed)}")
    print(
        f"Failed/unconfirmed:  "
        f"{len(estops) - len(confirmed)}"
    )

    if not effects:
        print("No confirmed E-stop measurements.")
        return

    print("\nE-stop command-to-effect latency:")
    print(f"  Mean: {statistics.mean(effects):.3f} ms")
    print(f"  p50:  {percentile(effects, 50):.3f} ms")
    print(f"  p95:  {percentile(effects, 95):.3f} ms")
    print(f"  p99:  {percentile(effects, 99):.3f} ms")
    print(f"  Max:  {max(effects):.3f} ms")

    print("\nE-stop command-to-confirmation latency:")
    print(
        f"  Mean: "
        f"{statistics.mean(confirmations):.3f} ms"
    )
    print(
        f"  p50:  "
        f"{percentile(confirmations, 50):.3f} ms"
    )
    print(
        f"  p95:  "
        f"{percentile(confirmations, 95):.3f} ms"
    )
    print(
        f"  p99:  "
        f"{percentile(confirmations, 99):.3f} ms"
    )
    print(f"  Max:  {max(confirmations):.3f} ms")

    late = sum(value > 200 for value in effects)

    print(
        f"\nE-stops above 200 ms: "
        f"{late}/{len(effects)}"
    )

    retried = sum(
        int(r["attempts"]) > 1
        for r in confirmed
    )

    print(
        f"E-stops requiring retries: "
        f"{retried}/{len(confirmed)}"
    )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--phase",
        choices=[
            "baseline",
            "normal",
            "degraded",
            "ack_loss",
        ],
        required=True,
    )

    parser.add_argument(
        "--trials",
        type=int,
        default=10,
    )

    parser.add_argument(
        "--interval",
        type=float,
        default=0.1,
        help="Pause between trials in seconds",
    )

    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=300,
    )

    parser.add_argument(
        "--retries",
        type=int,
        default=3,
    )

    args = parser.parse_args()

    if args.trials < 1:
        parser.error("--trials must be >= 1")

    if args.interval < 0:
        parser.error("--interval must be >= 0")

    if args.timeout_ms <= 0 or args.retries < 0:
        parser.error("Invalid timeout or retry count")

    experiment_id = f"{args.phase}_{time.time_ns()}"

    print(f"Experiment ID: {experiment_id}")
    print(f"Phase: {args.phase}")
    print(f"Trials: {args.trials}")
    print(f"CSV: {OUTPUT}")
    print()

    results = []

    for trial in range(1, args.trials + 1):
        print(f"[Trial {trial}/{args.trials}]")

        # Reset before each independent E-stop.
        for command in ("reset", "estop"):
            row = execute_command(
                command=command,
                phase=args.phase,
                trial=trial,
                experiment_id=experiment_id,
                timeout_ms=args.timeout_ms,
                retries=args.retries,
            )

            append_result(row)
            results.append(row)

            print(
                f"  {command.upper():5s} "
                f"status={row['ack_status'] or '-':10s} "
                f"effect={str(row['effect_latency_ms']):>8s} ms "
                f"confirm={str(row['confirmation_latency_ms']):>8s} ms "
                f"attempts={row['attempts']}"
            )

            if row["outcome"] != "CONFIRMED":
                print(
                    f"\nABORT: {command.upper()} failed: "
                    f"{row['error']}"
                )
                print(
                    "Robot state may be uncertain. "
                    "Inspect B3 before continuing."
                )
                print_summary(results)
                return 1

        if trial < args.trials:
            time.sleep(args.interval)

    print_summary(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
