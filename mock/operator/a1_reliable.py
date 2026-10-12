
import argparse
import json
import struct
import time

import zenoh

PORT = 7447

COMMAND_TOPIC = "teleop/commands/reliable"
ACK_TOPIC = "teleop/commands/reliable_ack"

COMMAND_FORMAT = struct.Struct("!QBQ")
ACK_FORMAT = struct.Struct("!QBQ")

E_STOP = 1
RESET = 2

ACK_NAMES = {
    1: "APPLIED",
    2: "DUPLICATE",
    3: "OLD_COMMAND",
    4: "REJECTED",
}


def connect():
    config = {
        "mode": "client",
        "connect": {
            "endpoints": [f"tcp/127.0.0.1:{PORT}"]
        },
        "scouting": {"multicast": {"enabled": False}},
    }
    return zenoh.open(
        zenoh.Config.from_json5(json.dumps(config))
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--command",
        choices=["estop", "reset"],
        default="estop",
    )
    parser.add_argument(
        "--duplicate",
        action="store_true",
        help="Send the same command ID twice",
    )
    args = parser.parse_args()

    opcode = E_STOP if args.command == "estop" else RESET

    # Unique and increasing across sequential test invocations
    # on this machine, assuming monotonic clock continuity.
    command_id = time.monotonic_ns()
    created_ns = time.monotonic_ns()

    payload = COMMAND_FORMAT.pack(
        command_id,
        opcode,
        created_ns,
    )

    with connect() as session:
        publisher = session.declare_publisher(
            COMMAND_TOPIC
        )

        def on_ack(sample):
            data = sample.payload.to_bytes()

            if len(data) != ACK_FORMAT.size:
                return

            ack_id, status, effect_ns = (
                ACK_FORMAT.unpack(data)
            )

            if ack_id != command_id:
                return

            print(
                f"[A1] ACK id={ack_id} "
                f"status={ACK_NAMES.get(status, status)}",
                flush=True,
            )

            if status in (1, 2):
                effect_latency_ms = (
                    effect_ns - created_ns
                ) / 1e6

                print(
                    "[A1] Command-to-effect latency: "
                    f"{effect_latency_ms:.3f} ms",
                    flush=True,
                )

        ack_sub = session.declare_subscriber(
            ACK_TOPIC, on_ack
        )

        # Allow local subscriptions to settle.
        time.sleep(0.3)

        print(
            f"[A1] Sending {args.command} "
            f"id={command_id}",
            flush=True,
        )

        publisher.put(payload)

        if args.duplicate:
            time.sleep(0.1)
            print("[A1] Sending duplicate command")
            publisher.put(payload)

        # Keep the subscriber alive to receive acknowledgments.
        time.sleep(2.0)


if __name__ == "__main__":
    main()
