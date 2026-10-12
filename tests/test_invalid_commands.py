
import json
import struct
import time

import zenoh

TOPIC = "teleop/commands/motion"
FORMAT = struct.Struct("!QQ84s")


def connect():
    config = {
        "mode": "client",
        "connect": {
            "endpoints": ["tcp/127.0.0.1:7447"]
        },
        "scouting": {
            "multicast": {"enabled": False}
        },
    }

    return zenoh.open(
        zenoh.Config.from_json5(json.dumps(config))
    )


def send(publisher, sequence, age_ms=0):
    timestamp_ns = time.monotonic_ns() - int(age_ms * 1e6)

    payload = FORMAT.pack(
        sequence,
        timestamp_ns,
        struct.pack("!f", 0.5).ljust(84, b"\x00")
    )

    publisher.put(payload)

    print(f"Sent seq={sequence}, age={age_ms} ms")


def main():
    with connect() as session:
        publisher = session.declare_publisher(TOPIC)

        # Allow subscriptions to establish.
        time.sleep(0.5)

        # Use a fresh B3 process with no competing A1 publisher.
        send(publisher, 100, age_ms=0)
        time.sleep(0.05)

        send(publisher, 101, age_ms=170)
        time.sleep(0.05)

        send(publisher, 99, age_ms=0)
        time.sleep(0.05)

        send(publisher, 102, age_ms=0)
        time.sleep(0.5)


if __name__ == "__main__":
    main()
