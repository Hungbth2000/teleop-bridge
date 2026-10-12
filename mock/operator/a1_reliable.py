
import argparse
import json
import struct
import threading
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
        "--id",
        type=int,
        default=None,
        help="Reuse an ID to test duplicate handling",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=300,
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
    )
    args = parser.parse_args()

    if args.timeout_ms <= 0 or args.retries < 0:
        parser.error("timeout must be positive; retries >= 0")

    opcode = E_STOP if args.command == "estop" else RESET
    command_id = (
        args.id if args.id is not None
        else time.time_ns()
    )

    if not 0 <= command_id < (1 << 63):
        parser.error("command ID must fit signed 64-bit SQLite")

    ack_received = threading.Event()
    ack_result = {}
    ack_lock = threading.Lock()

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

            with ack_lock:
                if ack_received.is_set():
                    print("[A1] Extra ACK received", flush=True)
                    return

                ack_result["status"] = status
                ack_result["effect_ns"] = effect_ns
                ack_received.set()

        ack_sub = session.declare_subscriber(
            ACK_TOPIC, on_ack
        )

        time.sleep(0.3)

        # Record command creation immediately before
        # the first transmission, not before setup.
        created_ns = time.monotonic_ns()

        payload = COMMAND_FORMAT.pack(
            command_id, opcode, created_ns
        )

        attempts = args.retries + 1

        for attempt in range(1, attempts + 1):
            print(
                f"[A1] Sending {args.command} "
                f"id={command_id} attempt={attempt}",
                flush=True,
            )

            publisher.put(payload)

            if ack_received.wait(args.timeout_ms / 1000):
                break

            print(
                f"[A1] ACK timeout after "
                f"{args.timeout_ms} ms",
                flush=True,
            )

        if not ack_received.is_set():
            print(
                "[A1] RESULT: UNCONFIRMED "
                "(effect may or may not have occurred)",
                flush=True,
            )
            return

        with ack_lock:
            status = ack_result["status"]
            effect_ns = ack_result["effect_ns"]

        print(
            f"[A1] ACK: {ACK_NAMES.get(status, status)}",
            flush=True,
        )

        if status in (1, 2):
            latency_ms = (effect_ns - created_ns) / 1e6
            print(
                f"[A1] Original command-to-effect: "
                f"{latency_ms:.3f} ms",
                flush=True,
            )


if __name__ == "__main__":
    main()
