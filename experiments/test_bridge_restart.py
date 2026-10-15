
#!/usr/bin/env python3

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
import csv
import shutil
import json


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "results" / "restart_test"
BRIDGE = ROOT / "build" / "teleop_bridge"


def timestamp():
    return time.monotonic_ns()



def start_bridge(role, log_file):
    """Start a hybrid bridge in the appropriate network namespace."""

    env = os.environ.copy()
    env["TELEOP_TRANSPORT"] = "hybrid"

    if role == "robot":
        env["TELEOP_TCP_HOST"] = "10.200.1.1"
        env["TELEOP_UDP_LOCAL"] = "10.200.1.2"
        env["TELEOP_UDP_PEER"] = "10.200.1.1"

        command = [
            "ip", "netns", "exec", "teleop-robot",
            str(BRIDGE), role,
        ]
    else:
        env["TELEOP_TCP_BIND"] = "10.200.1.1"
        env["TELEOP_UDP_LOCAL"] = "10.200.1.1"
        env["TELEOP_UDP_PEER"] = "10.200.1.2"

        command = [str(BRIDGE), role]

    return subprocess.Popen(
        command,
        cwd=ROOT,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def stop_process(process, sig=signal.SIGTERM):
    """Stop a process group and wait for it to exit."""
    if process is None or process.poll() is not None:
        return

    try:
        os.killpg(process.pid, sig)
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def analyze_head_recovery(restart_ns, bridge_started_ns):
    """Measure recovery using validated head-video frame arrivals."""

    csv_path = ROOT / "results" / "video_frames_rx.csv"

    if not csv_path.exists():
        print("[RECOVERY] No head-video receiver CSV found")
        return

    frames = []

    with csv_path.open(newline="") as f:
        for row in csv.DictReader(f):
            try:
                frames.append({
                    "capture_ns": int(row["capture_ns"]),
                    "event_ns": int(row["event_ns"]),
                    "frame_id": int(row["frame_id"]),
                    "latency_ms": float(row["latency_ms"]),
                })
            except (ValueError, KeyError):
                continue

    # Only count frames captured after the restart event.
    recovered = [
        frame
        for frame in frames
        if (
            frame["capture_ns"] >= restart_ns
            and frame["event_ns"] >= bridge_started_ns
        )
    ]

    if not recovered:
        print("[RECOVERY] No fresh head frame received after restart")
        return

    first = min(recovered, key=lambda frame: frame["event_ns"])

    recovery_ms = (
        first["event_ns"] - restart_ns
    ) / 1_000_000

    after_start_ms = (
        first["event_ns"] - bridge_started_ns
    ) / 1_000_000

    print("\n========== HEAD VIDEO RECOVERY ==========")
    print(f"First recovered frame ID: {first['frame_id']}")
    print(f"Frame latency: {first['latency_ms']:.3f} ms")
    print(f"Recovery from restart: {recovery_ms:.3f} ms")
    print(f"Recovery after bridge launch: {after_start_ms:.3f} ms")
    print(f"Recovery below 1000 ms: {recovery_ms < 1000}")


def main():
    parser = argparse.ArgumentParser(
        description="Test robot or operator bridge restart recovery."
    )

    parser.add_argument(
        "--restart",
        choices=["robot", "operator"],
        default="robot",
        help="Which bridge to restart (default: robot)",
    )

    parser.add_argument(
        "--duration",
        type=float,
        default=30.0,
        help="Integrated workload duration in seconds (default: 30)",
    )

    args = parser.parse_args()
    role = args.restart

    if os.geteuid() != 0:
        parser.error(
            "Run this experiment with sudo -E"
        )

    if args.duration <= 15:
        parser.error("--duration must be greater than 15 seconds")

    if not BRIDGE.is_file():
        raise SystemExit(f"Bridge binary not found: {BRIDGE}")

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    head_csv = ROOT / "results" / "video_frames_rx.csv"

    if head_csv.exists():
        backup_path = LOG_DIR / "video_frames_rx_before_restart.csv"
        shutil.copy2(head_csv, backup_path)
        head_csv.unlink()

    bridge_log_path = LOG_DIR / f"{role}_bridge.log"
    runner_log_path = LOG_DIR / f"runner_{role}.log"

    with (
        bridge_log_path.open("w", encoding="utf-8") as bridge_log,
        runner_log_path.open("w", encoding="utf-8") as runner_log,
    ):
        bridge = None
        runner = None

        try:
            # Start the bridge selected by --restart.
            bridge = start_bridge(role, bridge_log)

            print(
                f"[TEST] {role.capitalize()} bridge PID: {bridge.pid}",
                flush=True,
            )

            # Allow the bridge connection to establish.
            time.sleep(2)

            if bridge.poll() is not None:
                raise RuntimeError(
                    f"{role.capitalize()} bridge exited during startup"
                )

            # Start the existing integrated workload.
            runner = subprocess.Popen(
                [
                    sys.executable,
                    "experiments/run_three_cameras.py",
                    "--duration",
                    str(args.duration),
                    "--robot-netns",
                    "teleop-robot",
                ],
                cwd=ROOT,
                stdout=runner_log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

            print(
                f"[TEST] Runner PID: {runner.pid}",
                flush=True,
            )

            # The runner waits 2 seconds before starting senders.
            # Restart approximately 10 seconds into active traffic.
            time.sleep(12)

            if runner.poll() is not None:
                raise RuntimeError(
                    "Integrated experiment finished unexpectedly"
                )

            if bridge.poll() is not None:
                raise RuntimeError(
                    f"{role.capitalize()} bridge exited before restart"
                )

            # Simulate an abrupt bridge crash.
            t0 = timestamp()

            os.killpg(bridge.pid, signal.SIGKILL)
            bridge.wait(timeout=3)

            t_stopped = timestamp()

            # Keep the bridge offline for five seconds.
            time.sleep(5)

            # Start a replacement bridge.
            t1 = timestamp()
            bridge = start_bridge(role, bridge_log)

            events = {
                "role": role,
                "kill_ns": t0,
                "exit_ns": t_stopped,
                "restart_launch_ns": t1,
                "planned_downtime_seconds": 5,
                "transport": "hybrid",
            }

            events_path = LOG_DIR / f"{role}_restart_events.json"
            events_path.write_text(
                json.dumps(events, indent=2) + "\n"
            )

            print(
                f"[TEST] Restarted role: {role}",
                flush=True,
            )
            print(
                f"[TEST] Old bridge terminated at {t0}",
                flush=True,
            )
            print(
                f"[TEST] Old bridge exited at {t_stopped}",
                flush=True,
            )
            print(
                f"[TEST] New bridge started at {t1}",
                flush=True,
            )
            print(
                "[TEST] Termination-to-start gap: "
                f"{(t1 - t0) / 1e6:.3f} ms",
                flush=True,
            )

            # Confirm the replacement remains alive.
            time.sleep(0.1)

            if bridge.poll() is not None:
                raise RuntimeError(
                    f"Replacement {role} bridge exited unexpectedly. "
                    f"Check {bridge_log_path}"
                )

            # Wait for the integrated experiment to finish.
            result = runner.wait(
                timeout=max(45.0, args.duration + 15.0)
            )

            print(
                f"[TEST] Runner exit code: {result}",
                flush=True,
            )

            analyze_head_recovery(
                restart_ns=t0,
                bridge_started_ns=t1,
            )

            if result != 0:
                raise RuntimeError(
                    f"Integrated runner failed with exit code {result}"
                )

            print(
                f"[TEST] Bridge log: {bridge_log_path}",
                flush=True,
            )
            print(
                f"[TEST] Runner log: {runner_log_path}",
                flush=True,
            )

        finally:
            # Stop the runner first so all workload processes
            # have a chance to finish.
            if runner is not None and runner.poll() is None:
                stop_process(runner, signal.SIGINT)

            # Stop only the bridge managed by this test.
            stop_process(bridge)


if __name__ == "__main__":
    main()
