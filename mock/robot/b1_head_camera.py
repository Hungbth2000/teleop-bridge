#!/usr/bin/env python3

"""B1 — Head-camera publisher."""

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

SENDER = (
    ROOT
    / "mock"
    / "video"
    / "head_adaptive_sender.py"
)


def main():
    command = [
        sys.executable,
        str(SENDER),
        *sys.argv[1:],
    ]

    os.chdir(ROOT)
    os.execv(sys.executable, command)


if __name__ == "__main__":
    main()
