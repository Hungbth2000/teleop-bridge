#!/usr/bin/env python3

import json
import secrets
import struct
import time
from pathlib import Path

import zenoh

TOPIC = "teleop/commands/motion"
COMMAND_FORMAT = struct.Struct("!QQ84s")
MOTION_DATA_FORMAT = struct.Struct("!fQ72s")

assert COMMAND_FORMAT.size == 100
assert MOTION_DATA_FORMAT.size == 84


def main():
    config = {
        "mode": "client",
        "connect": {
            "endpoints": ["tcp/127.0.0.1:7447"]
        },
        "scouting": {
            "multicast": {"enabled": False}
        },
    }

    session_id = secrets.randbits(64)

    evidence = Path(
        "results/task2/fast_commands_tcp_udp/"
        "safety_tests/duplicate_reordered"
    )
    evidence.mkdir(parents=True, exist_ok=True)

    (evidence / "session_id.txt").write_text(
        str(session_id) + "\n"
    )

    with zenoh.open(
        zenoh.Config.from_json5(json.dumps(config))
    ) as session:

        publisher = session.declare_publisher(TOPIC)

        # Allow subscriptions and bridge forwarding to settle.
        time.sleep(0.5)

        for sequence, label in [
            (100, "valid"),
            (100, "duplicate"),
            (99, "reordered"),
        ]:
            motion_data = MOTION_DATA_FORMAT.pack(
                0.5,
                session_id,
                bytes(72),
            )

            payload = COMMAND_FORMAT.pack(
                sequence,
                time.monotonic_ns(),
                motion_data,
            )

            publisher.put(payload)

            print(
                f"[TEST] {label}: "
                f"session={session_id} "
                f"sequence={sequence}",
                flush=True,
            )

            time.sleep(0.1)

        time.sleep(0.5)


if __name__ == "__main__":
    main()
