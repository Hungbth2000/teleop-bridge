
#!/usr/bin/env python3

import argparse
import os
import signal
import subprocess
import sys
import time
import fcntl
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "results" / "three_camera_logs"


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--duration",
        type=float,
        default=75.0,
    )

    parser.add_argument(
        "--robot-netns",
        type=str,
        default=None,
        help="Network namespace for robot-side camera senders",
    )

    args = parser.parse_args()

    if args.duration <= 0:
        parser.error("Duration must be positive")

    lock_path = ROOT / "results" / ".three_camera_runner.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    lock_file = lock_path.open("w")
    try:
        fcntl.flock(
            lock_file.fileno(),
            fcntl.LOCK_EX | fcntl.LOCK_NB
        )
    except BlockingIOError:
        raise RuntimeError(
            "Another three-camera experiment is already running"
        )

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Use the current virtual environment.
    python = sys.executable
 
    receivers = {
        "a2_viewer": [
            python,
            "mock/operator/a2_viewer.py",
            "--save-h264",
        ],
        "a3_state": [
            python,
            "mock/operator/a3_state.py",
            "--duration",
            str(args.duration + 2),
        ],
    }

    senders = {
        "head_tx": [
            python,
            "mock/robot/b1_head_camera.py",
            "--duration",
            str(args.duration),
        ],
        "wrists_tx": [
            python,
            "mock/robot/b2_wrist_cameras.py",
            "--duration",
            str(args.duration),
        ],
        "a3_queries": [
            python,
            "experiments/query_workload.py",
            "--duration",
            str(args.duration),
            "--interval",
            "1",
            "--output",
            "results/query_workload.csv",
        ],
    }

    processes = {}
    log_files = {}

    robot_processes = {"head_tx", "wrists_tx"}

    def prepare_command(name, command):
        # When started through sudo, run ordinary processes
        # under the original user rather than root.
        user = os.environ.get("SUDO_USER")

        if args.robot_netns is not None and name in robot_processes:
            if os.geteuid() != 0:
                raise RuntimeError(
                    "--robot-netns requires running the runner with sudo"
                )

            return [
                "ip",
                "netns",
                "exec",
                args.robot_netns,
                "runuser",
                "-u",
                user,
                "--",
                *command,
            ]

        if user and os.geteuid() == 0:
            return [
                "runuser",
                "-u",
                user,
                "--",
                *command,
            ]

        return command

    def start_process(name, command):
        path = LOG_DIR / f"{name}.log"

        log_file = path.open("w", encoding="utf-8")
        log_files[name] = log_file

        process = subprocess.Popen(
            prepare_command(name, command),
            cwd=ROOT,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

        processes[name] = process

        print(
            f"[RUNNER] Started {name} "
            f"pid={process.pid} "
            f"log={path}",
            flush=True,
        )

    def stop_process(name):
        process = processes[name]

        def signal_group(sig):
            try:
                os.killpg(process.pid, sig)
                return True
            except ProcessLookupError:
                # The process group has already exited.
                return False

        # Signal the entire process group, even when the
        # original group leader has already exited.
        signal_group(signal.SIGINT)

        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            signal_group(signal.SIGTERM)

            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                signal_group(signal.SIGKILL)
                process.wait()

        # The leader may have exited before its children.
        # Give remaining members of its process group time
        # to finish their shutdown handlers.
        for _ in range(30):
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                break

            time.sleep(0.1)
        else:
            # Remaining descendants did not exit promptly.
            signal_group(signal.SIGTERM)
            time.sleep(0.2)
            signal_group(signal.SIGKILL)

    try:
        print("[RUNNER] Starting receivers...")

        for name, command in receivers.items():
            start_process(name, command)

        # Give Zenoh subscriptions time to initialize.
        time.sleep(2)

        print("[RUNNER] Starting A1 motion commands...")

        start_process(
            "a1_motion",
            [
                python,
                "mock/operator/a1_commands.py",
            ],
        )

        print("[RUNNER] Starting senders...")

        for name, command in senders.items():
            start_process(name, command)

        # Wait until all senders have finished.
        for name in senders:
            process = processes[name]
            return_code = process.wait()

            print(
                f"[RUNNER] {name} finished "
                f"exit={return_code}",
                flush=True,
            )

        # Stop continuous A1 motion after the finite workloads.
        print("[RUNNER] Stopping A1 motion...")
        stop_process("a1_motion")

        # Allow in-flight fragments to arrive.
        time.sleep(2)

    except KeyboardInterrupt:
        print(
            "\n[RUNNER] Interrupted",
            flush=True,
        )

    finally:
        print("[RUNNER] Stopping processes...")

        for name in processes:
            stop_process(name)

        for log_file in log_files.values():
            log_file.close()

        lock_file.close()

        print("[RUNNER] Finished.", flush=True)


if __name__ == "__main__":
    main()
