
#!/usr/bin/env python3

import json
import secrets
import struct
import time

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

    with zenoh.open(
        zenoh.Config.from_json5(json.dumps(config))
    ) as session:

        publisher = session.declare_publisher(TOPIC)

        # Deliberately older than the 150 ms limit.
        created_ns = time.monotonic_ns() - 200_000_000

        motion_data = MOTION_DATA_FORMAT.pack(
            0.5,
            secrets.randbits(64),
            bytes(72),
        )

        payload = COMMAND_FORMAT.pack(
            0,
            created_ns,
            motion_data,
        )

        publisher.put(payload)

        print("[TEST] Sent one stale motion command")
        print("[TEST] Intended age: at least 200 ms")
        print("[TEST] Payload size:", len(payload))

        # Allow Zenoh time to transmit before closing.
        time.sleep(0.5)


if __name__ == "__main__":
    main()
