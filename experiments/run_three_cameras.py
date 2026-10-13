
#!/usr/bin/env python3

import argparse
import os
import signal
import subprocess
import sys
import time
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

    args = parser.parse_args()

    if args.duration <= 0:
        parser.error("Duration must be positive")

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Use the current virtual environment.
    python = sys.executable
 
    receivers = {
        "head_rx": [
            python,
            "mock/video/head_receiver.py",
            "--format",
            "h264",
            "--save-h264",
            "results/final_validation/head_received.h264",
        ],
        "left_rx": [
            python,
            "mock/video/wrist_receiver.py",
            "--camera",
            "left",
            "--save-h264",
            "results/final_validation/wrist_left_received.h264",
        ],
        "right_rx": [
            python,
            "mock/video/wrist_receiver.py",
            "--camera",
            "right",
            "--save-h264",
            "results/final_validation/wrist_right_received.h264",
        ],
    }

    senders = {
        "head_tx": [
            python,
            "mock/video/head_adaptive_sender.py",
            "--duration",
            str(args.duration),
        ],
        "left_tx": [
            python,
            "mock/video/wrist_adaptive_sender.py",
            "--camera",
            "left",
            "--duration",
            str(args.duration),
        ],
        "right_tx": [
            python,
            "mock/video/wrist_adaptive_sender.py",
            "--camera",
            "right",
            "--duration",
            str(args.duration),
        ],
    }

    processes = {}
    log_files = {}

    def start_process(name, command):
        path = LOG_DIR / f"{name}.log"

        log_file = path.open("w", encoding="utf-8")
        log_files[name] = log_file

        process = subprocess.Popen(
            command,
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

        if process.poll() is not None:
            return

        # Send Ctrl+C to the process group so that
        # receiver finally blocks can close CSVs.
        try:
            os.killpg(
                process.pid,
                signal.SIGINT,
            )

            process.wait(timeout=5)

        except subprocess.TimeoutExpired:
            os.killpg(
                process.pid,
                signal.SIGTERM,
            )

            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(
                    process.pid,
                    signal.SIGKILL,
                )
                process.wait()

    try:
        print("[RUNNER] Starting receivers...")

        for name, command in receivers.items():
            start_process(name, command)

        # Give Zenoh subscriptions time to initialize.
        time.sleep(2)

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

        print("[RUNNER] Finished.", flush=True)


if __name__ == "__main__":
    main()
