import os
import sqlite3
from pathlib import Path

import json
import statistics
import struct
import threading
import time

import zenoh

PORT = 7448

MOTION_TOPIC = "teleop/commands/motion"
RELIABLE_TOPIC = "teleop/commands/reliable"
ACK_TOPIC = "teleop/commands/reliable_ack"

MOTION_FORMAT = struct.Struct("!QQ84s")
COMMAND_FORMAT = struct.Struct("!QBQ")
ACK_FORMAT = struct.Struct("!QBQ")

E_STOP = 1
RESET = 2

ACK_APPLIED = 1
ACK_DUPLICATE = 2
ACK_OLD = 3
ACK_REJECTED = 4

MAX_COMMAND_AGE_NS = 150_000_000
WATCHDOG_NS = 300_000_000

lock = threading.RLock()

last_sequence = -1
last_fresh_time_ns = None

robot_moving = False

command_ages_ms = []
accepted = 0
rejected_stale = 0
rejected_sequence = 0
blocked_by_estop = 0
watchdog_events = 0

# Test-only fault injection: drop the first ACK
# for a newly applied reliable command.
DROP_FIRST_ACK = os.getenv("TELEOP_DROP_FIRST_ACK", "0") == "1"
dropped_ack_ids = set()

DB_PATH = Path("results/b3_commands.sqlite3")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.execute("PRAGMA synchronous=FULL")

db.execute("""
CREATE TABLE IF NOT EXISTS controller_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_command_id INTEGER NOT NULL,
    estop_latched INTEGER NOT NULL,
    last_effect_ns INTEGER NOT NULL
)
""")

# Conservative startup: an uninitialized controller is stopped.
db.execute("""
INSERT OR IGNORE INTO controller_state
(id, last_command_id, estop_latched, last_effect_ns)
VALUES (1, -1, 1, 0)
""")

db.commit()

row = db.execute("""
SELECT last_command_id, estop_latched, last_effect_ns
FROM controller_state
WHERE id = 1
""").fetchone()

last_reliable_id = row[0]
estop_latched = bool(row[1])
last_reliable_effect_ns = row[2]

print(
    f"[B3] Restored state: last_id={last_reliable_id} "
    f"estop={estop_latched}",
    flush=True,
)

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


def percentile(values, p):
    if not values:
        return 0.0

    values = sorted(values)
    index = (len(values) - 1) * p / 100
    low = int(index)
    high = min(low + 1, len(values) - 1)
    fraction = index - low

    return (
        values[low] * (1 - fraction)
        + values[high] * fraction
    )


def on_motion(sample):
    global last_sequence, last_fresh_time_ns
    global robot_moving, accepted
    global rejected_stale, rejected_sequence
    global blocked_by_estop

    data = sample.payload.to_bytes()

    if len(data) != MOTION_FORMAT.size:
        print("[B3] Invalid motion payload", flush=True)
        return

    sequence, created_ns, motion_data = (
        MOTION_FORMAT.unpack(data)
    )

    now_ns = time.monotonic_ns()
    age_ns = now_ns - created_ns

    with lock:
        if age_ns < 0 or age_ns > MAX_COMMAND_AGE_NS:
            rejected_stale += 1
            return

        if sequence <= last_sequence:
            rejected_sequence += 1
            return

        # Remember the newest valid sequence even during E-stop.
        last_sequence = sequence

        if estop_latched:
            blocked_by_estop += 1
            return

        velocity = struct.unpack(
            "!f", motion_data[:4]
        )[0]

        last_fresh_time_ns = now_ns
        command_ages_ms.append(age_ns / 1e6)
        accepted += 1
        robot_moving = abs(velocity) > 0.0001



def make_reliable_callback(ack_publisher):
    def on_reliable(sample):
        global last_reliable_id
        global last_reliable_effect_ns
        global estop_latched, robot_moving
        global last_fresh_time_ns

        data = sample.payload.to_bytes()

        if len(data) != COMMAND_FORMAT.size:
            print("[B3] Invalid reliable payload", flush=True)
            return

        command_id, opcode, created_ns = (
            COMMAND_FORMAT.unpack(data)
        )

        with lock:
            now_ns = time.monotonic_ns()

            if command_id == last_reliable_id:
                status = ACK_DUPLICATE
                effect_ns = last_reliable_effect_ns

            elif command_id < last_reliable_id:
                status = ACK_OLD
                effect_ns = now_ns

            elif opcode in (E_STOP, RESET):
                new_estop_state = (opcode == E_STOP)

                try:
                    # Commit the simulated state transition
                    # before reporting successful execution.
                    db.execute("""
                        UPDATE controller_state
                        SET last_command_id = ?,
                            estop_latched = ?,
                            last_effect_ns = ?
                        WHERE id = 1
                    """, (
                        command_id,
                        int(new_estop_state),
                        now_ns,
                    ))
                    db.commit()

                except sqlite3.Error as exc:
                    db.rollback()
                    print(
                        f"[B3] Persistence failure: {exc}",
                        flush=True,
                    )
                    # Never acknowledge successful execution
                    # if the state was not committed.
                    return

                last_reliable_id = command_id
                last_reliable_effect_ns = now_ns
                estop_latched = new_estop_state

                # Both E-stop and reset leave robot stopped.
                robot_moving = False
                last_fresh_time_ns = None

                status = ACK_APPLIED
                effect_ns = now_ns  # Fix: timestamp of original execution

                action = (
                    "E-STOP APPLIED"
                    if opcode == E_STOP
                    else "E-STOP RESET"
                )
                print(
                    f"[B3] {action} id={command_id}",
                    flush=True,
                )

            else:
                status = ACK_REJECTED
                effect_ns = now_ns

            ack = ACK_FORMAT.pack(
                command_id, status, effect_ns
            )

        # Fault injection: simulate losing the first ACK
        # after the command has already been committed.
        if (
            DROP_FIRST_ACK
            and status == ACK_APPLIED
            and command_id not in dropped_ack_ids
        ):
            dropped_ack_ids.add(command_id)

            print(
                f"[B3] TEST: Dropping first ACK "
                f"for id={command_id}",
                flush=True,
            )
            return

        # Send normal ACK, including for duplicate commands.
        ack_publisher.put(ack)

        print(
            f"[B3] ACK id={command_id} status={status}",
            flush=True,
        )

    return on_reliable


def main():
    global robot_moving, watchdog_events

    with connect() as session:
        ack_publisher = session.declare_publisher(
            ACK_TOPIC
        )

        motion_sub = session.declare_subscriber(
            MOTION_TOPIC, on_motion
        )

        reliable_sub = session.declare_subscriber(
            RELIABLE_TOPIC,
            make_reliable_callback(ack_publisher)
        )

        print("[B3] Connected to robot router")
        print("[B3] Motion and E-stop handlers active")

        last_report = time.monotonic_ns()

        try:
            while True:
                now_ns = time.monotonic_ns()

                with lock:
                    if (
                        robot_moving
                        and last_fresh_time_ns is not None
                        and now_ns - last_fresh_time_ns
                        >= WATCHDOG_NS
                    ):
                        robot_moving = False
                        watchdog_events += 1
                        print(
                            "[B3] WATCHDOG -> STOP",
                            flush=True,
                        )

                    if now_ns - last_report >= 1_000_000_000:
                        p50 = percentile(
                            command_ages_ms, 50
                        )
                        p95 = percentile(
                            command_ages_ms, 95
                        )
                        p99 = percentile(
                            command_ages_ms, 99
                        )

                    if last_fresh_time_ns is None:
                        command_status = "WAITING"
                    else:
                        silence_ms = (
                            now_ns - last_fresh_time_ns
                        ) / 1e6

                        command_status = (
                            "ACTIVE"
                            if silence_ms < 300
                            else "TIMEOUT"
                        )                   

                        print(
                            f"[B3] status={command_status} "
                            f"accepted={accepted} "
                            f"estop={estop_latched} "
                            f"moving={robot_moving} "
                            f"age_ms p50={p50:.2f} "
                            f"p95={p95:.2f} "
                            f"p99={p99:.2f}",
                            flush=True,
                        )

                        last_report = now_ns

                time.sleep(0.005)

        except KeyboardInterrupt:
            with lock:
                robot_moving = False
            print("\n[B3] Controller stopped")


if __name__ == "__main__":
    main()
