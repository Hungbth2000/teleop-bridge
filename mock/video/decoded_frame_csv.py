
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

FIELDS = [
    "stream_id",
    "frame_id",
    "capture_ns",
    "reassembly_ns",
    "decoded_ns",
    "reassembly_latency_ms",
    "decode_latency_ms",
    "within_200ms",
]


class DecodedFrameCsv:
    def __init__(self, camera):
        self.path = (
            ROOT / "results" /
            f"decoded_frames_{camera}.csv"
        )

        self.path.parent.mkdir(parents=True, exist_ok=True)

        self.file = self.path.open(
            "w", newline="", encoding="utf-8"
        )

        self.writer = csv.DictWriter(
            self.file, fieldnames=FIELDS
        )
        self.writer.writeheader()

    def log(self, complete_frame, decoded):
        self.writer.writerow({
            "stream_id": decoded["stream_id"],
            "frame_id": decoded["frame_id"],
            "capture_ns": decoded["capture_ns"],
            "reassembly_ns": decoded["reassembly_ns"],
            "decoded_ns": decoded["decoded_ns"],
            "reassembly_latency_ms": round(
                complete_frame.latency_ms, 6
            ),
            "decode_latency_ms": round(
                decoded["latency_ms"], 6
            ),
            "within_200ms": int(
                decoded["within_200ms"]
            ),
        })

    def close(self):
        self.file.close()
