#!/usr/bin/env python3

"""A3: Monitor robot-state updates from B3."""

import argparse
import json
import struct
import threading
import time

import zenoh


PORT = 7447
STATE_TOPIC = "teleop/robot/state"

# Must match B3's state format.
STATE_FORMAT = struct.Struct("!QQqffBB")


def percentile(values, p):
    if not values:
        return 0.0

    ordered = sorted(values)
    position = (len(ordered) - 1) * p / 100

    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower

    return (
        ordered[lower] * (1 - fraction)
        + ordered[upper] * fraction
    )


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
    parser = argparse.ArgumentParser(
        description="A3 robot-state monitor"
    )

    parser.add_argument(
        "--duration",
        type=float,
        default=10.0,
        help="Measurement duration in seconds",
    )

    args = parser.parse_args()

    if args.duration <= 0:
        parser.error("Duration must be positive")

    mutex = threading.Lock()

    state = {
        "received": 0,
        "missing": 0,
        "out_of_order": 0,
        "invalid": 0,
        "last_sequence": None,
        "last_applied": -1,
        "moving": False,
        "estop": True,
        "ages_ms": [],
    }

    def on_state(sample):
        data = sample.payload.to_bytes()

        if len(data) != STATE_FORMAT.size:
            with mutex:
                state["invalid"] += 1
            return

        (
            sequence,
            created_ns,
            applied_sequence,
            joint_1,
            joint_2,
            moving,
            estop,
        ) = STATE_FORMAT.unpack(data)

        age_ms = (
            time.monotonic_ns() - created_ns
        ) / 1e6

        with mutex:
            previous = state["last_sequence"]

            if previous is not None:
                if sequence <= previous:
                    state["out_of_order"] += 1
                elif sequence > previous + 1:
                    state["missing"] += (
                        sequence - previous - 1
                    )

            if previous is None or sequence > previous:
                state["last_sequence"] = sequence
                state["last_applied"] = applied_sequence
                state["moving"] = bool(moving)
                state["estop"] = bool(estop)

            state["received"] += 1
            state["ages_ms"].append(age_ms)

    with connect() as session:
        subscriber = session.declare_subscriber(
            STATE_TOPIC,
            on_state,
        )

        print(
            "[A3] Connected to operator router",
            flush=True,
        )

        print(
            f"[A3] Monitoring state for "
            f"{args.duration:.1f}s",
            flush=True,
        )

        try:
            time.sleep(args.duration)

        except KeyboardInterrupt:
            print(
                "\n[A3] Interrupted",
                flush=True,
            )

        with mutex:
            ages = list(state["ages_ms"])
            received = state["received"]

            print("\n[A3] FINAL STATE REPORT")
            print(f"  Received: {received}")
            print(f"  Missing: {state['missing']}")
            print(
                "  Out-of-order/duplicate: "
                f"{state['out_of_order']}"
            )
            print(f"  Invalid: {state['invalid']}")
            print(
                "  Last applied motion sequence: "
                f"{state['last_applied']}"
            )
            print(f"  Moving: {state['moving']}")
            print(f"  E-stop latched: {state['estop']}")

            if ages:
                print(
                    f"  State age p50: "
                    f"{percentile(ages, 50):.3f} ms"
                )
                print(
                    f"  State age p95: "
                    f"{percentile(ages, 95):.3f} ms"
                )
                print(
                    f"  State age p99: "
                    f"{percentile(ages, 99):.3f} ms"
                )
            else:
                print("  No state messages received")


if __name__ == "__main__":
    main()