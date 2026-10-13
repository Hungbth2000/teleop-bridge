
import atexit
import csv
import queue
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

        RESULTS_DIR.mkdir(parents=True, exist_ok=True)

        self._queue = queue.Queue()
        self._closed = False
        self._lock = threading.Lock()
        self._error = None

        # The writer is a daemon so it cannot prevent
        # interpreter shutdown unexpectedly.
        #
        # Normal shutdown is handled by close(),
        # which waits for queued events to be written.
        self._writer = threading.Thread(
            target=self._writer_loop,
            name=f"control-csv-{role}",
            daemon=True,
        )

        self._writer.start()

        # Covers normal script termination, including
        # returning from main() and KeyboardInterrupt.
        atexit.register(self.close)

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
        # Capture both clocks on the caller thread.
        # Disk I/O is delegated to the worker.
        wall_ns = time.time_ns()
        now_ns = time.monotonic_ns()

        row = {
            "wall_time_ns": wall_ns,
            "monotonic_ns": (
                event_ns
                if event_ns is not None
                else now_ns
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

        with self._lock:
            if self._closed:
                raise RuntimeError(
                    "Cannot log after ControlEventLogger.close()"
                )

            # No filesystem operations on the caller thread.
            self._queue.put_nowait(row)

    def _writer_loop(self):
        try:
            write_header = (
                not self.path.exists()
                or self.path.stat().st_size == 0
            )

            with self.path.open("a", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=FIELDS,
                )

                if write_header:
                    writer.writeheader()
                    f.flush()

                while True:
                    row = self._queue.get()

                    if row is None:
                        break

                    writer.writerow(row)

                    # Flush each event so experiments can
                    # inspect records while B3 is running.
                    f.flush()

        except Exception as exc:
            self._error = exc

    def close(self):
        with self._lock:
            if self._closed:
                return

            self._closed = True

            # FIFO queue: all previously enqueued rows
            # are processed before this sentinel.
            self._queue.put_nowait(None)

        self._writer.join()

        if self._error is not None:
            raise RuntimeError(
                f"Control-event CSV writer failed: {self._error}"
            ) from self._error

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
