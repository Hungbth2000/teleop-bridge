#!/usr/bin/env python3

"""A2 — Receive and record all three camera streams."""

import argparse
import signal
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(
        description="A2 three-camera receiver"
    )

    parser.add_argument(
        "--save-h264",
        action="store_true",
        help="Save reconstructed H.264 streams",
    )

    args = parser.parse_args()

    output_dir = ROOT / "results" / "final_validation"

    receivers = {
        "head": [
            sys.executable,
            "mock/video/head_receiver.py",
            "--format",
            "h264",
        ],
        "left": [
            sys.executable,
            "mock/video/wrist_receiver.py",
            "--camera",
            "left",
        ],
        "right": [
            sys.executable,
            "mock/video/wrist_receiver.py",
            "--camera",
            "right",
        ],
    }

    if args.save_h264:
        output_dir.mkdir(parents=True, exist_ok=True)

        names = {
            "head": "head_received.h264",
            "left": "wrist_left_received.h264",
            "right": "wrist_right_received.h264",
        }

        for camera, command in receivers.items():
            command.extend([
                "--save-h264",
                str(output_dir / names[camera]),
            ])

    processes = {}

    try:
        for camera, command in receivers.items():
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                start_new_session=True,
            )

            processes[camera] = process

            print(
                f"[A2] Started {camera} receiver "
                f"pid={process.pid}",
                flush=True,
            )

        # A2 runs until stopped by the experiment runner.
        for process in processes.values():
            process.wait()

    except KeyboardInterrupt:
        print("\n[A2] Stopping receivers.", flush=True)

    finally:
        for process in processes.values():
            if process.poll() is None:
                process.send_signal(signal.SIGINT)

        for process in processes.values():
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

        print("[A2] Receivers stopped.", flush=True)


if __name__ == "__main__":
    main()
