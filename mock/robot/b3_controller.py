import os
import sqlite3
from pathlib import Path

import json
import statistics
import struct
import threading
import time

import zenoh
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1])
)

from control_event_log import ControlEventLogger

event_logger = ControlEventLogger("b3")

PORT = 7448

MOTION_TOPIC = "teleop/commands/motion"
RELIABLE_TOPIC = "teleop/commands/reliable"
ACK_TOPIC = "teleop/commands/reliable_ack"

STATE_TOPIC = "teleop/robot/state"
QUERY_TOPIC = "teleop/robot/config"

STATE_HZ = 50
STATE_PERIOD_NS = 1_000_000_000 // STATE_HZ

STATE_FORMAT = struct.Struct("!QQqffBB")

MOTION_FORMAT = struct.Struct("!QQ84s")
# Velocity + A1 sender session ID + reserved bytes.
MOTION_DATA_FORMAT = struct.Struct("!fQ72s")

assert MOTION_DATA_FORMAT.size == 84
COMMAND_FORMAT = struct.Struct("!QBQ")
ACK_FORMAT = struct.Struct("!QBQ")

E_STOP = 1
RESET = 2

ACK_APPLIED = 1
ACK_DUPLICATE = 2
ACK_OLD = 3
ACK_REJECTED = 4

MAX_COMMAND_AGE_NS = 150_000_000
# Trigger before the 300 ms safety deadline to allow
# margin for the 5 ms polling loop and OS scheduling.
WATCHDOG_NS = 280_000_000

lock = threading.RLock()

last_sequence = -1
active_motion_session = None
retired_motion_sessions = set()
last_applied_motion_sequence = -1
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

def on_config_query(query):
    """Answer A3's robot configuration queries."""

    # Test-only delay to simulate a slow queryable.
    delay_ms = int(os.environ.get("B3_QUERY_DELAY_MS", "0"))

    if delay_ms > 0:
        time.sleep(delay_ms / 1000.0)

    configuration = {
        "node": "B3",
        "motion_frequency_hz": 100,
        "state_frequency_hz": 50,
        "max_command_age_ms": 150,
        "watchdog_ms": 300,
    }

    payload = json.dumps(configuration).encode("utf-8")

    query.reply(
        QUERY_TOPIC,
        payload,
    )

    print(
        "[B3] Replied to configuration query",
        flush=True,
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

    global active_motion_session
    global retired_motion_sessions

    global last_applied_motion_sequence

    data = sample.payload.to_bytes()

    if len(data) != MOTION_FORMAT.size:
        print("[B3] Invalid motion payload", flush=True)
        return

    sequence, created_ns, motion_data = (
        MOTION_FORMAT.unpack(data)
    )

    velocity, session_id, _reserved = (
        MOTION_DATA_FORMAT.unpack(motion_data)
    )

    now_ns = time.monotonic_ns()
    age_ns = now_ns - created_ns

    with lock:
        if age_ns < 0 or age_ns > MAX_COMMAND_AGE_NS:
            rejected_stale += 1

            if rejected_stale <= 5:
                print(
                    f"[B3 DEBUG] Stale motion: "
                    f"sequence={sequence}, "
                    f"age_ms={age_ns / 1e6:.2f}",
                    flush=True,
                )
            return

        # Reject commands from sessions that have already
        # relinquished control.
        if session_id in retired_motion_sessions:
            rejected_sequence += 1
            return

        if active_motion_session is None:
            # First sender since B3 started.
            active_motion_session = session_id
            last_sequence = -1

            print(
                f"[B3 SESSION] Initial session={session_id}",
                flush=True,
            )

        elif session_id != active_motion_session:
            # Do not replace a sender while the robot is moving.
            if robot_moving or estop_latched:
                rejected_sequence += 1
                return

            # Retire the previous sender so delayed messages
            # from that session can never regain control.
            retired_motion_sessions.add(active_motion_session)

            print(
                f"[B3 SESSION] Handover "
                f"old={active_motion_session} "
                f"new={session_id}",
                flush=True,
            )

            active_motion_session = session_id
            last_sequence = -1

        # Sequence numbers must increase within a sender session.
        if sequence <= last_sequence:
            rejected_sequence += 1

            if rejected_sequence <= 5:
                print(
                    f"[B3 DEBUG] Rejected motion sequence: "
                    f"received={sequence}, "
                    f"last={last_sequence}",
                    flush=True,
                )

            return

        # Remember the newest valid sequence even during E-stop.
        last_sequence = sequence

        if estop_latched:
            blocked_by_estop += 1
            return

        # Detect the first accepted command after an interruption.
        gap_ms = (
            (now_ns - last_fresh_time_ns) / 1e6
            if last_fresh_time_ns is not None
            else None
        )

        last_fresh_time_ns = now_ns
        command_ages_ms.append(age_ns / 1e6)
        accepted += 1
        last_applied_motion_sequence = sequence
        robot_moving = abs(velocity) > 0.0001

        if gap_ms is None or gap_ms > 50:
            print(
                f"[B3 MOTION RECOVERY] "
                f"accepted={accepted} "
                f"sequence={sequence} "
                f"accepted_ns={now_ns} "
                f"previous_gap_ms={gap_ms}",
                flush=True,
            )

        # Keep the existing periodic diagnostic timestamps.
        if accepted % 100 == 0:
            print(
                f"[B3 MOTION] accepted={accepted} "
                f"sequence={sequence} "
                f"accepted_ns={now_ns}",
                flush=True,
            )



def make_reliable_callback(ack_publisher):
    def on_reliable(sample):
        global last_reliable_id
        global last_reliable_effect_ns
        global estop_latched, robot_moving
        global last_fresh_time_ns

        data = sample.payload.to_bytes()

        print(
            f"[B3 DEBUG] Reliable callback invoked "
            f"payload_bytes={len(data)} "
            f"received_at_ns={time.monotonic_ns()}",
            flush=True,
        )

        if len(data) != COMMAND_FORMAT.size:
            print("[B3] Invalid reliable payload", flush=True)
            return

        command_id, opcode, created_ns = (
            COMMAND_FORMAT.unpack(data)
        )

        opcode_name = (
            "ESTOP" if opcode == E_STOP
            else "RESET" if opcode == RESET
            else f"UNKNOWN_{opcode}"
        )

        event_logger.log(
            event="COMMAND_RECEIVED",
            command_id=command_id,
            opcode=opcode_name,
            created_ns=created_ns,
        )

        print(
            f"[B3 DEBUG] command_id={command_id} "
            f"opcode={opcode}",
            flush=True,
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

        status_names = {
            ACK_APPLIED: "APPLIED",
            ACK_DUPLICATE: "DUPLICATE",
            ACK_OLD: "OLD_COMMAND",
            ACK_REJECTED: "REJECTED",
        }

        result_status = status_names.get(
            status, str(status)
        )

        event_logger.log(
            event=(
                "APPLIED"
                if status == ACK_APPLIED
                else "DUPLICATE"
                if status == ACK_DUPLICATE
                else "NOT_APPLIED"
            ),
            command_id=command_id,
            opcode=opcode_name,
            status=result_status,
            created_ns=created_ns,
            effect_ns=effect_ns,
            event_ns=(
                effect_ns
                if status == ACK_APPLIED
                else time.monotonic_ns()
            ),
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

            # Record the deliberately dropped ACK.
            event_logger.log(
                event="ACK_SUPPRESSED",
                command_id=command_id,
                opcode=opcode_name,
                status=result_status,
                created_ns=created_ns,
                effect_ns=effect_ns,
                event_ns=effect_ns,
            )
            return

        # Send normal ACK, including for duplicate commands.
        ack_publisher.put(ack)

        # Record successful publication.
        event_logger.log(
            event="ACK_PUBLISHED",
            command_id=command_id,
            opcode=opcode_name,
            status=result_status,
            created_ns=created_ns,
            effect_ns=effect_ns,
        )

        print(
            f"[B3] ACK id={command_id} status={status}",
            flush=True,
        )

    return on_reliable


def main():
    global robot_moving, watchdog_events

    with connect() as session:

        config_queryable = session.declare_queryable(
            QUERY_TOPIC,
            on_config_query,
        )

        ack_publisher = session.declare_publisher(
            ACK_TOPIC
        )

        state_publisher = session.declare_publisher(
            STATE_TOPIC
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

        state_sequence = 0
        next_state_ns = time.monotonic_ns()

        try:
            while True:
                now_ns = time.monotonic_ns()

                if now_ns >= next_state_ns:
                    with lock:
                        applied_sequence = last_applied_motion_sequence
                        moving = robot_moving
                        estop = estop_latched

                    # Deterministic simulated joint positions.
                    joint_1 = float(state_sequence % 360) / 100.0
                    joint_2 = float((state_sequence * 2) % 360) / 100.0

                    state_payload = STATE_FORMAT.pack(
                        state_sequence,
                        now_ns,
                        applied_sequence,
                        joint_1,
                        joint_2,
                        int(moving),
                        int(estop),
                    )

                    state_publisher.put(state_payload)

                    state_sequence += 1

                    # Skip missed publish slots instead of bursting.
                    next_state_ns = max(
                        next_state_ns + STATE_PERIOD_NS,
                        time.monotonic_ns(),
                    )

                with lock:
                    if (
                        robot_moving
                        and last_fresh_time_ns is not None
                        and now_ns - last_fresh_time_ns
                        >= WATCHDOG_NS
                    ):
                        robot_moving = False
                        watchdog_events += 1
                        elapsed_ms = (
                            now_ns - last_fresh_time_ns
                        ) / 1e6

                        print(
                            f"[B3 WATCHDOG] "
                            f"last_motion_ns={last_fresh_time_ns} "
                            f"stop_ns={now_ns} "
                            f"elapsed_ms={elapsed_ms:.3f} "
                            f"threshold_ms={WATCHDOG_NS / 1e6:.0f} "
                            f"moving={robot_moving}",
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
                                if silence_ms < WATCHDOG_NS / 1e6
                                else "TIMEOUT"
                            )

                        print(
                            f"[B3] status={command_status} "
                            f"accepted={accepted} "
                            f"rejected_stale={rejected_stale} "
                            f"rejected_sequence={rejected_sequence} "
                            f"blocked_by_estop={blocked_by_estop} "
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
