
from pathlib import Path


class H264Recorder:
    """
    Offline recorder for validated H.264 access units.

    Stores received frames and writes them in
    frame-number order, skipping missing frames.
    """

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.run_prefix = None
        self.frames = {}

        self.duplicates = 0
        self.other_runs = 0
        self.closed = False

    def add_frame(self, frame_id, data):
        if self.closed:
            raise RuntimeError("Recorder is closed")

        run_prefix = frame_id >> 32
        frame_number = frame_id & 0xFFFFFFFF

        if self.run_prefix is None:
            self.run_prefix = run_prefix

        if run_prefix != self.run_prefix:
            self.other_runs += 1
            return

        if frame_number in self.frames:
            self.duplicates += 1
            return

        self.frames[frame_number] = bytes(data)

    def close(self):
        if self.closed:
            return

        self.closed = True
        numbers = sorted(self.frames)

        missing = []

        if numbers:
            last = numbers[-1]
            received = set(numbers)

            missing = [
                number
                for number in range(last + 1)
                if number not in received
            ]

        with self.path.open("wb") as output:
            for number in numbers:
                output.write(self.frames[number])

        print(
            f"[H264 REC] Saved: {self.path}",
            flush=True,
        )
        print(
            f"[H264 REC] Frames written: "
            f"{len(numbers)}",
            flush=True,
        )
        print(
            f"[H264 REC] Missing frames: "
            f"{len(missing)}",
            flush=True,
        )
        print(
            f"[H264 REC] Duplicates: "
            f"{self.duplicates}",
            flush=True,
        )
        print(
            f"[H264 REC] Other-run frames: "
            f"{self.other_runs}",
            flush=True,
        )

        if missing:
            print(
                f"[H264 REC] First missing frame: "
                f"{missing[0]}",
                flush=True,
            )
