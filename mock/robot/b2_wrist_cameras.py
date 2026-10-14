#!/usr/bin/env python3

"""B2 — Publish both wrist-camera streams."""

import argparse
import signal
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

SENDER = (
    ROOT
    / "mock"
    / "video"
    / "wrist_adaptive_sender.py"
)


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

    processes = []

    try:
        for camera in ("left", "right"):
            command = [
                sys.executable,
                str(SENDER),
                "--camera",
                camera,
                "--duration",
                str(args.duration),
            ]

            process = subprocess.Popen(
                command,
                cwd=ROOT,
            )

            processes.append(process)

            print(
                f"[B2] Started {camera} wrist camera "
                f"pid={process.pid}",
                flush=True,
            )

        results = []

        for process in processes:
            results.append(process.wait())

        if any(code != 0 for code in results):
            raise SystemExit(1)

        print(
            "[B2] Both wrist cameras completed.",
            flush=True,
        )

    except KeyboardInterrupt:
        print(
            "\n[B2] Interrupted.",
            flush=True,
        )

    finally:
        for process in processes:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)

        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    main()
