
#!/usr/bin/env python3

import json
import struct
import threading
import time

import zenoh
import argparse

from pathlib import Path

from frame_csv import VideoFrameCsv

from frame_protocol import (
    HEAD,
    FrameReassembler,
)

OPERATOR_PORT = 7447
VIDEO_TOPIC = "teleop/video/head/rx"


class H264Recorder:
    """Write received H.264 access units in frame order."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.file = self.path.open("wb")

        self.run_prefix = None
        self.next_frame = 0
        self.pending = {}

        self.written = 0
        self.duplicates = 0
        self.other_runs = 0

    def add_frame(self, frame_id, data):
        run_prefix = frame_id >> 32
        frame_number = frame_id & 0xFFFFFFFF

        # Record only one run per output file.
        if self.run_prefix is None:
            self.run_prefix = run_prefix

        if run_prefix != self.run_prefix:
            self.other_runs += 1
            return

        if frame_number < self.next_frame:
            self.duplicates += 1
            return

        if frame_number in self.pending:
            self.duplicates += 1
            return

        self.pending[frame_number] = data

        # Flush consecutive frames in their proper order.
        while self.next_frame in self.pending:
            frame = self.pending.pop(
                self.next_frame
            )

            self.file.write(frame)

            self.written += 1
            self.next_frame += 1

    def close(self):
        self.file.flush()
        self.file.close()

        print(
            f"[H264 REC] Saved: {self.path}",
            flush=True,
        )

        print(
            f"[H264 REC] Ordered frames written: "
            f"{self.written}",
            flush=True,
        )

        print(
            f"[H264 REC] Buffered out-of-order "
            f"frames: {len(self.pending)}",
            flush=True,
        )

        print(
            f"[H264 REC] Duplicate frames: "
            f"{self.duplicates}",
            flush=True,
        )

        print(
            f"[H264 REC] Other-run frames ignored: "
            f"{self.other_runs}",
            flush=True,
        )

        if self.pending:
            print(
                "[H264 REC] WARNING: Recording is "
                "incomplete because frame numbers "
                "are missing.",
                flush=True,
            )

            print(
                "[H264 REC] First missing frame: "
                f"{self.next_frame}",
                flush=True,
            )


def connect():
    config = {
        "mode": "client",
        "connect": {
            "endpoints": [
                f"tcp/127.0.0.1:{OPERATOR_PORT}"
            ]
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
        "--format",
        choices=["synthetic", "h264"],
        default="synthetic",
    )

    parser.add_argument(
        "--save-h264",
        type=Path,
        default=None,
        help="Save reconstructed H.264 access units",
    )

    args = parser.parse_args()

    if (
        args.save_h264 is not None
        and args.format != "h264"
    ):
        parser.error(
            "--save-h264 requires --format h264"
        )

    reassembler = FrameReassembler()

    lock = threading.Lock()

    valid_frames = 0
    corrupt_frames = 0
    last_latency_ms = 0.0
    last_frame_id = -1

    csv_log = VideoFrameCsv("rx")

    recorder = (
        H264Recorder(args.save_h264)
        if args.save_h264 is not None
        else None
    )

    def on_video(sample):
        nonlocal valid_frames
        nonlocal corrupt_frames
        nonlocal last_latency_ms
        nonlocal last_frame_id

        received_ns = time.monotonic_ns()
        packet = sample.payload.to_bytes()

        with lock:
            result = reassembler.push(
                packet,
                received_ns=received_ns,
            )

            if result is None:
                return

            if result.stream_id != HEAD:
                return

            frame_id = result.frame_id
            data = result.data

            
            if args.format == "synthetic":
                expected = (
                    struct.pack("!Q", frame_id)
                    + bytes([frame_id % 251])
                    * (len(data) - 8)
                )

                payload_valid = data == expected

            else:
                # A basic Annex B access-unit check.
                # The frame protocol has already
                # verified total size and CRC32.
                payload_valid = (
                    data.startswith(b"\x00\x00\x01\x09")
                    or data.startswith(
                        b"\x00\x00\x00\x01\x09"
                    )
                )
        
            if not payload_valid:
                corrupt_frames += 1
                return

            valid_frames += 1
            last_latency_ms = result.latency_ms
            last_frame_id = frame_id

            # Save the validated encoded access unit.
            if recorder is not None:
                recorder.add_frame(
                    frame_id,
                    data,
                )

            # Log the received frame.
            run_prefix = frame_id >> 32
            frame_number = frame_id & 0xFFFFFFFF

            csv_log.log(
                run_id=f"{run_prefix:08x}",
                stream_id=result.stream_id,
                frame_id=frame_id,
                frame_number=frame_number,
                capture_ns=result.capture_ns,
                event_ns=result.completed_ns,
                frame_bytes=len(result.data),
                fragments=(
                    len(result.data) + 999
                ) // 1000,
                latency_ms=round(
                    result.latency_ms, 6
                ),
            )

    print(
        "[HEAD RX] Waiting for video fragments...",
        flush=True,
    )

    try:
        with connect() as session:
            subscriber = session.declare_subscriber(
                VIDEO_TOPIC,
                on_video,
            )

            try:
                while True:
                    time.sleep(1)

                    with lock:
                        reassembler.expire()

                        print(
                            f"[HEAD RX] "
                            f"complete={valid_frames} "
                            f"expired={reassembler.expired} "
                            f"invalid={reassembler.invalid} "
                            f"corrupt={corrupt_frames} "
                            f"last_id={last_frame_id} "
                            f"last_latency="
                            f"{last_latency_ms:.2f}ms",
                            flush=True,
                        )

            except KeyboardInterrupt:
                print(
                    "\n[HEAD RX] Stopped",
                    flush=True,
                )

    finally:
        # Close only after the zenoh session exits.
        try:
            csv_log.close()
        finally:
            if recorder is not None:
                with lock:
                    recorder.close()

        print(
            "[HEAD RX] Frame CSV saved",
            flush=True,
        )

if __name__ == "__main__":
    main()
