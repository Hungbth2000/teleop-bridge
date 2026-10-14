
#!/usr/bin/env python3

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "results" / "restart_test"
BRIDGE = ROOT / "build" / "teleop_bridge"


def timestamp():
    return time.monotonic_ns()


def start_bridge(role, log_file):
    """Start one bridge process in its own process group."""
    return subprocess.Popen(
        [str(BRIDGE), role],
        cwd=ROOT,
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

    if args.duration <= 15:
        parser.error("--duration must be greater than 15 seconds")

    if not BRIDGE.is_file():
        raise SystemExit(f"Bridge binary not found: {BRIDGE}")

    LOG_DIR.mkdir(parents=True, exist_ok=True)

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

            # Terminate the old bridge.
            t0 = timestamp()

            os.killpg(bridge.pid, signal.SIGTERM)
            bridge.wait(timeout=3)

            t_stopped = timestamp()

            # Launch the replacement bridge immediately.
            bridge = start_bridge(role, bridge_log)
            t1 = timestamp()

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
