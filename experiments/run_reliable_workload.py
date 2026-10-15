#!/usr/bin/env python3

import subprocess
import sys
import time
from pathlib import Path

COMMANDS = 22
INTERVAL_SECONDS = 3.0

SCRIPT = Path(__file__).resolve().parents[1] / \
    "mock/operator/a1_reliable.py"


def main():
    start = time.monotonic()
    failures = 0

    for i in range(COMMANDS):
        target = start + i * INTERVAL_SECONDS
        remaining = target - time.monotonic()

        if remaining > 0:
            time.sleep(remaining)

        command = "estop" if i % 2 == 0 else "reset"

        print(
            f"\n[WORKLOAD] {i + 1}/{COMMANDS} "
            f"command={command}",
            flush=True,
        )

        result = subprocess.run(
            [
                sys.executable,
                "-u",
                str(SCRIPT),
                "--command", command,
                "--timeout-ms", "300",
                "--retries", "3",
            ],
            check=False,
        )

        if result.returncode != 0:
            failures += 1
            print(
                f"[WORKLOAD] Process exited with "
                f"code={result.returncode}",
                flush=True,
            )

    print(
        f"\n[WORKLOAD] Finished. "
        f"Commands attempted={COMMANDS}, "
        f"process_errors={failures}",
        flush=True,
    )


if __name__ == "__main__":
    main()
