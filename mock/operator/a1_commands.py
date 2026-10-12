
import json
import math
import struct
import time

import zenoh

TOPIC = "teleop/commands/motion"
PORT = 7447

FREQUENCY_HZ = 100
PERIOD_NS = 1_000_000_000 // FREQUENCY_HZ

# 8-byte sequence + 8-byte timestamp + 84-byte payload.
COMMAND_FORMAT = struct.Struct("!QQ84s")
assert COMMAND_FORMAT.size == 100


def connect():
    config = {
        "mode": "client",
        "connect": {
            "endpoints": [f"tcp/127.0.0.1:{PORT}"]
        },
        "scouting": {
            "multicast": {"enabled": False}
        },
    }
    return zenoh.open(
        zenoh.Config.from_json5(json.dumps(config))
    )


def main():
    with connect() as session:
        publisher = session.declare_publisher(TOPIC)

        print("[A1] Connected to operator router")
        print("[A1] Publishing movement commands at 100 Hz")

        sequence = 0
        next_tick = time.monotonic_ns()

        try:
            while True:
                now = time.monotonic_ns()

                if now < next_tick:
                    time.sleep((next_tick - now) / 1e9)

                # Timestamp at command generation.
                timestamp_ns = time.monotonic_ns()

                # Deterministic simulated movement.
                velocity = math.sin(sequence * 0.01)

                motion_data = struct.pack("!f", velocity)
                motion_data = motion_data.ljust(84, b"\x00")

                payload = COMMAND_FORMAT.pack(
                    sequence,
                    timestamp_ns,
                    motion_data,
                )

                publisher.put(payload)

                if sequence % 100 == 0:
                    print(
                        f"[A1] seq={sequence} "
                        f"velocity={velocity:.3f} "
                        f"size={len(payload)} bytes",
                        flush=True,
                    )

                sequence += 1

                # Do not send a burst of old commands
                # if the process falls behind schedule.
                next_tick = max(
                    next_tick + PERIOD_NS,
                    time.monotonic_ns(),
                )

        except KeyboardInterrupt:
            print("\n[A1] Stopped")


if __name__ == "__main__":
    main()
