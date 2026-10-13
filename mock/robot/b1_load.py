
import argparse
import json
import struct
import time

import zenoh

PORT = 7448
TOPIC = "teleop/test/video_load"


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
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--hz",
        type=float,
        default=500.0,
    )

    parser.add_argument(
        "--size",
        type=int,
        default=1000,
        help="Payload size in bytes",
    )

    parser.add_argument(
        "--duration",
        type=float,
        default=75.0,
        help="Duration in seconds",
    )

    args = parser.parse_args()

    if args.hz <= 0 or args.size < 8 or args.duration <= 0:
        parser.error(
            "hz and duration must be positive; size >= 8"
        )

    period = 1.0 / args.hz

    # First eight bytes carry a monotonically increasing
    # synthetic message sequence number.
    padding = bytes(args.size - 8)

    sent = 0
    missed_slots = 0

    with connect() as session:
        publisher = session.declare_publisher(TOPIC)

        time.sleep(0.3)

        start = time.monotonic()
        next_send = start
        end = start + args.duration

        print(
            f"[B1 LOAD] Publishing {args.size}-byte "
            f"messages at {args.hz:.1f} Hz",
            flush=True,
        )

        while True:
            now = time.monotonic()

            if now >= end:
                break

            if now < next_send:
                time.sleep(next_send - now)
                continue

            payload = struct.pack("!Q", sent) + padding
            publisher.put(payload)
            sent += 1

            next_send += period

            # Skip missed time slots rather than generating
            # a burst of outdated messages.
            now = time.monotonic()
            if next_send < now:
                skipped = int(
                    (now - next_send) / period
                ) + 1
                missed_slots += skipped
                next_send += skipped * period

            if sent % 2500 == 0:
                elapsed = now - start

                print(
                    f"[B1 LOAD] sent={sent} "
                    f"elapsed={elapsed:.1f}s "
                    f"missed_slots={missed_slots}",
                    flush=True,
                )

        elapsed = time.monotonic() - start

        print(
            f"[B1 LOAD] Finished: "
            f"sent={sent}, "
            f"elapsed={elapsed:.2f}s, "
            f"missed_slots={missed_slots}",
            flush=True,
        )


if __name__ == "__main__":
    main()
