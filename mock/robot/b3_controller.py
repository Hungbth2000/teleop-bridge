
import json
import statistics
import struct
import time

import zenoh

TOPIC = "teleop/commands/motion"
PORT = 7448

MAX_COMMAND_AGE_NS = 150_000_000
WATCHDOG_NS = 300_000_000

COMMAND_FORMAT = struct.Struct("!QQ84s")

last_sequence = -1
last_fresh_time_ns = None

robot_moving = False
command_ages_ms = []

accepted = 0
rejected_stale = 0
rejected_sequence = 0
safety_violations = 0


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


def percentile(values, p):
    if not values:
        return 0.0

    sorted_values = sorted(values)
    index = (len(sorted_values) - 1) * p / 100
    lower = int(index)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = index - lower

    return (
        sorted_values[lower] * (1 - fraction)
        + sorted_values[upper] * fraction
    )


def on_command(sample):
    global last_sequence
    global last_fresh_time_ns
    global robot_moving, accepted
    global rejected_stale, rejected_sequence
    global safety_violations

    receive_time_ns = time.monotonic_ns()

    data = sample.payload.to_bytes()

    if len(data) != COMMAND_FORMAT.size:
        print("[B3] Invalid command size", flush=True)
        return

    sequence, timestamp_ns, motion_data = (
        COMMAND_FORMAT.unpack(data)
    )

    age_ns = receive_time_ns - timestamp_ns

    # Reject future timestamps as well.
    if age_ns < 0 or age_ns > MAX_COMMAND_AGE_NS:
        rejected_stale += 1
        return

    if sequence <= last_sequence:
        rejected_sequence += 1
        return

    # Validate before applying any motion.
    if age_ns > MAX_COMMAND_AGE_NS:
        safety_violations += 1
        return

    last_sequence = sequence
    last_fresh_time_ns = receive_time_ns
    command_ages_ms.append(age_ns / 1e6)

    velocity = struct.unpack("!f", motion_data[:4])[0]

    accepted += 1
    robot_moving = abs(velocity) > 0.0001


def main():
    global robot_moving

    with connect() as session:
        subscriber = session.declare_subscriber(
            TOPIC, on_command
        )

        print("[B3] Connected to robot router")
        print("[B3] Waiting for movement commands...")

        last_report_ns = time.monotonic_ns()

        try:
            while True:
                now_ns = time.monotonic_ns()

                if (
                    last_fresh_time_ns is not None
                    and now_ns - last_fresh_time_ns
                    >= WATCHDOG_NS
                    and robot_moving
                ):
                    robot_moving = False
                    print(
                        "[B3] WATCHDOG: No fresh commands "
                        "for 300 ms -> STOP",
                        flush=True,
                    )

                if now_ns - last_report_ns >= 1_000_000_000:
                    if command_ages_ms:
                        p50 = statistics.median(
                            command_ages_ms
                        )
                        p95 = percentile(command_ages_ms, 95)
                        p99 = percentile(command_ages_ms, 99)
                    else:
                        p50 = p95 = p99 = 0.0

                    print(
                        f"[B3] accepted={accepted} "
                        f"stale={rejected_stale} "
                        f"old_seq={rejected_sequence} "
                        f"age_ms p50={p50:.2f} "
                        f"p95={p95:.2f} "
                        f"p99={p99:.2f} "
                        f"moving={robot_moving}",
                        flush=True,
                    )

                    last_report_ns = now_ns

                time.sleep(0.01)

        except KeyboardInterrupt:
            robot_moving = False
            print(
                "\n[B3] Controller stopped",
                f"safety_violations={safety_violations}",
            )


if __name__ == "__main__":
    main()
