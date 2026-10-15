#!/usr/bin/env python3

import argparse
import csv
import json
from pathlib import Path


def read_csv(path):
    if not path.exists():
        raise FileNotFoundError(path)

    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def ms(later_ns, earlier_ns):
    return round((later_ns - earlier_ns) / 1_000_000, 3)


def analyze_video(path, kill_ns, restart_ns):
    rows = read_csv(path)

    frames = []
    for row in rows:
        try:
            frames.append({
                "frame_id": row["frame_id"],
                "capture_ns": int(row["capture_ns"]),
                "decoded_ns": int(row["decoded_ns"]),
                "latency_ms": float(row["decode_latency_ms"]),
                "good": row["within_200ms"] == "1",
            })
        except (ValueError, KeyError):
            continue

    before = [
        f for f in frames
        if f["decoded_ns"] < kill_ns and f["good"]
    ]

    recovered = [
        f for f in frames
        if f["capture_ns"] >= restart_ns
        and f["decoded_ns"] >= restart_ns
        and f["good"]
    ]

    last = max(before, key=lambda f: f["decoded_ns"]) if before else None
    first = min(recovered, key=lambda f: f["decoded_ns"]) if recovered else None

    return {
        "good_frames_before_kill": len(before),
        "good_frames_after_restart": len(recovered),
        "first_recovered_frame_id": first["frame_id"] if first else None,
        "first_recovered_decode_latency_ms": first["latency_ms"] if first else None,
        "recovery_after_launch_ms": ms(first["decoded_ns"], restart_ns) if first else None,
        "recovery_after_kill_ms": ms(first["decoded_ns"], kill_ns) if first else None,
        "last_to_first_good_frame_gap_ms": (
            ms(first["decoded_ns"], last["decoded_ns"])
            if first and last else None
        ),
        "recovered": first is not None,
    }


def analyze_motion(path, kill_ns, restart_ns):
    rows = read_csv(path)

    applied = []
    for row in rows:
        if row.get("decision") != "applied":
            continue
        if row.get("stale_at_reception") != "0":
            continue
        if not row.get("applied_ns"):
            continue

        try:
            applied.append({
                "session_id": row["session_id"],
                "sequence": int(row["sequence"]),
                "created_ns": int(row["created_ns"]),
                "applied_ns": int(row["applied_ns"]),
                "age_ms": float(row["latency_ms"]),
            })
        except (ValueError, KeyError):
            continue

    before = [
        m for m in applied
        if m["applied_ns"] < kill_ns
    ]

    recovered = [
        m for m in applied
        if m["created_ns"] >= restart_ns
        and m["applied_ns"] >= restart_ns
        and 0 <= m["age_ms"] <= 150
    ]

    last = max(before, key=lambda m: m["applied_ns"]) if before else None
    first = min(recovered, key=lambda m: m["applied_ns"]) if recovered else None

    return {
        "fresh_applied_before_kill": len(before),
        "fresh_applied_after_restart": len(recovered),
        "first_recovered_session_id": first["session_id"] if first else None,
        "first_recovered_sequence": first["sequence"] if first else None,
        "first_recovered_command_age_ms": first["age_ms"] if first else None,
        "recovery_after_launch_ms": ms(first["applied_ns"], restart_ns) if first else None,
        "recovery_after_kill_ms": ms(first["applied_ns"], kill_ns) if first else None,
        "last_to_first_applied_gap_ms": (
            ms(first["applied_ns"], last["applied_ns"])
            if first and last else None
        ),
        "recovered": first is not None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=["operator", "robot"], required=True)
    args = parser.parse_args()

    base = (
        Path("results/task2/recovery_tcp_udp")
        / f"{args.role}_bridge_restart"
    )

    events = json.loads((base / "restart_events.json").read_text())

    kill_ns = int(events["kill_ns"])
    restart_ns = int(events["restart_launch_ns"])

    video = {
        camera: analyze_video(
            base / f"decoded_frames_{camera}.csv",
            kill_ns,
            restart_ns,
        )
        for camera in ("head", "left", "right")
    }

    motion = analyze_motion(
        base / "motion_rx.csv",
        kill_ns,
        restart_ns,
    )

    recovery_values = [
        result["recovery_after_launch_ms"]
        for result in [*video.values(), motion]
        if result["recovery_after_launch_ms"] is not None
    ]

    all_recovered = (
        all(result["recovered"] for result in video.values())
        and motion["recovered"]
    )

    summary = {
        "role": args.role,
        "kill_ns": kill_ns,
        "restart_launch_ns": restart_ns,
        "bridge_downtime_ms": ms(restart_ns, kill_ns),
        "video": video,
        "motion": motion,
        "full_recovery_after_launch_ms": (
            max(recovery_values) if all_recovered else None
        ),
        "all_paths_recovered": all_recovered,
    }

    output = base / "recovery_summary.json"
    output.write_text(json.dumps(summary, indent=2) + "\n")

    print(json.dumps(summary, indent=2))
    print("\nRESULT:", "RECOVERED" if all_recovered else "INCOMPLETE")
    print("Saved:", output)


if __name__ == "__main__":
    main()
