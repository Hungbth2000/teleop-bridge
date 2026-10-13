
import csv
import threading
import time
from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parents[1] / "results"

FIELDS = [
    "wall_time_ns",
    "monotonic_ns",
    "role",
    "event",
    "command_id",
    "opcode",
    "attempt",
    "status",
    "created_ns",
    "effect_ns",
]


class ControlEventLogger:
    def __init__(self, role):
        self.role = role
        self.path = RESULTS_DIR / f"control_events_{role}.csv"
        self.lock = threading.Lock()

        RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        event,
        command_id,
        opcode,
        attempt="",
        status="",
        created_ns="",
        effect_ns="",
        event_ns=None,
    ):
        row = {
            "wall_time_ns": time.time_ns(),
            "monotonic_ns": (
                event_ns
                if event_ns is not None
                else time.monotonic_ns()
            ),
            "role": self.role,
            "event": event,
            "command_id": command_id,
            "opcode": opcode,
            "attempt": attempt,
            "status": status,
            "created_ns": created_ns,
            "effect_ns": effect_ns,
        }

        # Separate files per process role.
        # Serialize writes within each process.
        with self.lock:
            write_header = (
                not self.path.exists()
                or self.path.stat().st_size == 0
            )

            with self.path.open("a", newline="") as f:
                writer = csv.DictWriter(
                    f, fieldnames=FIELDS
                )

                if write_header:
                    writer.writeheader()

                writer.writerow(row)
