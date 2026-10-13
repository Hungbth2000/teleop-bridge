
import argparse
import json
import struct
import sys
import threading
import time
from pathlib import Path

import zenoh

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1])
)

from control_event_log import ControlEventLogger


PORT = 7447

COMMAND_TOPIC = "teleop/commands/reliable"
ACK_TOPIC = "teleop/commands/reliable_ack"

# uint64 command_id, uint8 opcode, uint64 created_ns
COMMAND_FORMAT = struct.Struct("!QBQ")

# uint64 command_id, uint8 status, uint64 effect_ns
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
        parser.error(
            "timeout must be positive; retries >= 0"
        )

    opcode = (
        E_STOP if args.command == "estop"
        else RESET
    )

    opcode_name = args.command.upper()

    command_id = (
        args.id
        if args.id is not None
        else time.time_ns()
    )

    # SQLite uses signed 64-bit integers.
    if not 0 <= command_id < (1 << 63):
        parser.error(
            "command ID must fit signed 64-bit SQLite"
        )

    ack_received = threading.Event()
    ack_result = {}
    ack_lock = threading.Lock()

    logger = ControlEventLogger("a1")

    with connect() as session:

        publisher = session.declare_publisher(
            COMMAND_TOPIC
        )

        def on_ack(sample):
            # Capture the timestamp immediately upon
            # callback entry, before parsing or logging.
            received_ns = time.monotonic_ns()

            data = sample.payload.to_bytes()

            if len(data) != ACK_FORMAT.size:
                print(
                    f"[A1] Invalid ACK size: "
                    f"{len(data)} bytes",
                    flush=True,
                )
                return

            ack_id, status, effect_ns = (
                ACK_FORMAT.unpack(data)
            )

            status_name = ACK_NAMES.get(
                status, str(status)
            )

            # Ignore ACKs from other commands.
            if ack_id != command_id:
                print(
                    "[A1] ACK for different command: "
                    f"received_id={ack_id}, "
                    f"expected_id={command_id}, "
                    f"status={status_name}",
                    flush=True,
                )
                return

            # Store the ACK before performing
            # synchronous CSV I/O.
            with ack_lock:

                if ack_received.is_set():
                    first_status = ack_result["status"]
                    first_effect_ns = ack_result["effect_ns"]
                    is_extra = True

                else:
                    ack_result["status"] = status
                    ack_result["effect_ns"] = effect_ns
                    ack_result["received_ns"] = received_ns

                    ack_received.set()
                    is_extra = False

            # Use the actual callback timestamp
            # rather than the time of CSV writing.
            logger.log(
                event="ACK_RECEIVED",
                command_id=ack_id,
                opcode=opcode_name,
                status=status_name,
                effect_ns=effect_ns,
                event_ns=received_ns,
            )

            if is_extra:
                print(
                    f"[A1] EXTRA ACK:\n"
                    f"  command_id={ack_id}\n"
                    f"  status={status_name}\n"
                    f"  effect_ns={effect_ns}\n"
                    f"  same_status="
                    f"{status == first_status}\n"
                    f"  same_effect_ns="
                    f"{effect_ns == first_effect_ns}\n"
                    f"  received_at_ns={received_ns}",
                    flush=True,
                )

            else:
                print(
                    f"[A1] FIRST ACK:\n"
                    f"  command_id={ack_id}\n"
                    f"  status={status_name}\n"
                    f"  effect_ns={effect_ns}\n"
                    f"  received_at_ns={received_ns}",
                    flush=True,
                )

        ack_sub = session.declare_subscriber(
            ACK_TOPIC,
            on_ack,
        )

        # Give the subscription time to become active.
        time.sleep(0.3)

        # Create the original command timestamp once.
        # All retries must reuse the same payload and ID.
        created_ns = time.monotonic_ns()

        payload = COMMAND_FORMAT.pack(
            command_id,
            opcode,
            created_ns,
        )

        attempts = args.retries + 1

        for attempt in range(1, attempts + 1):

            print(
                f"[A1] Sending {args.command} "
                f"id={command_id} "
                f"attempt={attempt}",
                flush=True,
            )

            # Log the transmission attempt.
            # The timestamp is not proof of delivery.
            logger.log(
                event="SENT",
                command_id=command_id,
                opcode=opcode_name,
                attempt=attempt,
                created_ns=created_ns,
            )

            publisher.put(payload)

            if ack_received.wait(
                args.timeout_ms / 1000.0
            ):
                break

            # Avoid a false timeout if the ACK arrives
            # just as the wait expires.
            if ack_received.is_set():
                break

            print(
                f"[A1] ACK timeout after "
                f"{args.timeout_ms} ms",
                flush=True,
            )

            logger.log(
                event="TIMEOUT",
                command_id=command_id,
                opcode=opcode_name,
                attempt=attempt,
                created_ns=created_ns,
            )

        # No matching ACK received.
        if not ack_received.is_set():

            logger.log(
                event="UNCONFIRMED",
                command_id=command_id,
                opcode=opcode_name,
                created_ns=created_ns,
            )

            print(
                "[A1] RESULT: UNCONFIRMED "
                "(effect may or may not have occurred)",
                flush=True,
            )
            return

        # Read the first ACK atomically.
        with ack_lock:
            status = ack_result["status"]
            effect_ns = ack_result["effect_ns"]
            received_ns = ack_result["received_ns"]

        status_name = ACK_NAMES.get(
            status, str(status)
        )

        # Use actual ACK reception time for
        # the CONFIRMED event as well.
        logger.log(
            event="CONFIRMED",
            command_id=command_id,
            opcode=opcode_name,
            status=status_name,
            created_ns=created_ns,
            effect_ns=effect_ns,
            event_ns=received_ns,
        )

        print(
            f"[A1] ACK: {status_name}",
            flush=True,
        )

        # Confirmation latency is meaningful for
        # every ACK status, including REJECTED.
        confirmation_ms = (
            received_ns - created_ns
        ) / 1e6

        if status in (1, 2) and effect_ns > 0:

            effect_latency_ms = (
                effect_ns - created_ns
            ) / 1e6

            print(
                "[A1] Original command-to-effect: "
                f"{effect_latency_ms:.3f} ms",
                flush=True,
            )

        print(
            "[A1] Command-to-confirmation: "
            f"{confirmation_ms:.3f} ms",
            flush=True,
        )


if __name__ == "__main__":
    main()
