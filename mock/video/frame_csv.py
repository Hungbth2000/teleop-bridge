
import csv
import queue
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"

FIELDS = [
    "run_id",
    "stream_id",
    "frame_id",
    "frame_number",
    "capture_ns",
    "event_ns",
    "frame_bytes",
    "fragments",
    "latency_ms",
]


class VideoFrameCsv:
    def __init__(self, role):
        if role not in ("tx", "rx"):
            raise ValueError("Role must be tx or rx")

        RESULTS.mkdir(parents=True, exist_ok=True)

        self.path = RESULTS / f"video_frames_{role}.csv"
        self.queue = queue.Queue()
        self.error = None
        self.closed = False

        self.worker = threading.Thread(
            target=self._write_loop,
            name=f"video-csv-{role}",
            daemon=True,
        )
        self.worker.start()

    def log(self, **values):
        if self.closed:
            raise RuntimeError("VideoFrameCsv is closed")

        row = {
            field: values.get(field, "")
            for field in FIELDS
        }

        self.queue.put_nowait(row)

    def _write_loop(self):
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

                while True:
                    row = self.queue.get()

                    if row is None:
                        break

                    writer.writerow(row)

                f.flush()

        except Exception as exc:
            self.error = exc

    def close(self):
        if self.closed:
            return

        self.closed = True
        self.queue.put_nowait(None)
        self.worker.join()

        if self.error is not None:
            raise RuntimeError(
                f"Video CSV writer failed: {self.error}"
            ) from self.error

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
