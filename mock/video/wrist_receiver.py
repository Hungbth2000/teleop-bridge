
#!/usr/bin/env python3

import argparse
import csv
import json
import sys
import threading
import time
from pathlib import Path

from frame_decoder import FrameDecoder
from decoded_frame_csv import DecodedFrameCsv

import zenoh

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mock.video.frame_protocol import (
    LEFT_WRIST,
    RIGHT_WRIST,
    FrameReassembler,
)

from mock.video.h264_recorder import H264Recorder

CAMERAS = {
    "left": {
        "id": LEFT_WRIST,
        "topic": "teleop/video/wrist_left/rx",
    },
    "right": {
        "id": RIGHT_WRIST,
        "topic": "teleop/video/wrist_right/rx",
    },
}

CSV_FIELDS = [
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


def connect():
    config = {
        "mode": "client",
        "connect": {
            "endpoints": ["tcp/127.0.0.1:7447"]
        },
        "scouting": {
            "multicast": {
                "enabled": False
            }
        },
    }

    return zenoh.open(
        zenoh.Config.from_json5(json.dumps(config))
    )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--camera",
        choices=["left", "right"],
        required=True,
    )

    parser.add_argument(
        "--save-h264",
        type=Path,
        default=None,
        help="Save reconstructed H.264 access units",
    )

    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Optional CSV output path",
    )

    args = parser.parse_args()
    camera = CAMERAS[args.camera]

    recorder = (
        H264Recorder(args.save_h264)
        if args.save_h264 is not None
        else None
    )

    csv_path = (
        args.csv
        if args.csv is not None
        else ROOT / "results" /
            f"video_frames_rx_wrist_{args.camera}.csv"
    )

    csv_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    reassembler = FrameReassembler()

    decoder = FrameDecoder(640, 360)
    decode_csv = DecodedFrameCsv(args.camera)

    lock = threading.Lock()

    completed_ids = set()
    corrupt = 0
    duplicates = 0
    last_latency = 0.0
    last_frame_number = -1

    # Use append mode to preserve previous runs.
    csv_file = csv_path.open(
        "a",
        newline="",
        encoding="utf-8",
    )

    csv_writer = csv.DictWriter(
        csv_file,
        fieldnames=CSV_FIELDS,
    )

    if csv_file.tell() == 0:
        csv_writer.writeheader()

    def on_video(sample):
        nonlocal corrupt
        nonlocal duplicates
        nonlocal last_latency
        nonlocal last_frame_number

        packet = sample.payload.to_bytes()

        with lock:
            result = reassembler.push(
                packet,
                received_ns=time.monotonic_ns(),
            )

            if result is None:
                return

            if result.stream_id != camera["id"]:
                return

            data = result.data

            is_h264 = (
                data.startswith(b"\x00\x00\x01\x09")
                or data.startswith(
                    b"\x00\x00\x00\x01\x09"
                )
            )

            if not is_h264:
                corrupt += 1
                return

            if result.frame_id in completed_ids:
                duplicates += 1
                return

            completed_ids.add(result.frame_id)

            decoded = decoder.decode(result)

            if decoded is not None:
                decode_csv.log(result, decoded)

            if recorder is not None:
                recorder.add_frame(
                    result.frame_id,
                    data,
                )

            run_prefix = result.frame_id >> 32
            frame_number = (
                result.frame_id & 0xFFFFFFFF
            )

            last_frame_number = frame_number
            last_latency = result.latency_ms

            csv_writer.writerow({
                "run_id": f"{run_prefix:08x}",
                "stream_id": result.stream_id,
                "frame_id": result.frame_id,
                "frame_number": frame_number,
                "capture_ns": result.capture_ns,
                "event_ns": result.completed_ns,
                "frame_bytes": len(data),
                "fragments": (
                    len(data) + 999
                ) // 1000,
                "latency_ms": round(
                    result.latency_ms, 6
                ),
            })

    print(
        f"[WRIST RX] camera={args.camera} "
        "waiting for H264 frames...",
        flush=True,
    )

    print(
        f"[WRIST RX] CSV: {csv_path}",
        flush=True,
    )

    try:
        with connect() as session:
            subscriber = session.declare_subscriber(
                camera["topic"],
                on_video,
            )

            try:
                while True:
                    time.sleep(1)

                    with lock:
                        reassembler.expire()

                        # Flush periodically rather
                        # than after every frame.
                        csv_file.flush()

                        print(
                            f"[WRIST RX] "
                            f"camera={args.camera} "
                            f"complete={len(completed_ids)} "
                            f"expired={reassembler.expired} "
                            f"invalid={reassembler.invalid} "
                            f"corrupt={corrupt} "
                            f"duplicates={duplicates} "
                            f"last_frame={last_frame_number} "
                            f"last_latency="
                            f"{last_latency:.2f}ms",
                            flush=True,
                        )

            except KeyboardInterrupt:
                print(
                    f"\n[WRIST RX] Stopped "
                    f"camera={args.camera}",
                    flush=True,
                )

    finally:
        # The zenoh session has closed before
        # we close the CSV file.
        with lock:
            reassembler.expire()
            csv_file.flush()
            csv_file.close()

            decode_csv.close()

            if recorder is not None:
                recorder.close()

            print(
                f"[WRIST RX] FINAL "
                f"camera={args.camera} "
                f"complete={len(completed_ids)} "
                f"expired={reassembler.expired} "
                f"invalid={reassembler.invalid} "
                f"corrupt={corrupt} "
                f"duplicates={duplicates}",
                flush=True,
            )

            print(
                f"[WRIST RX] CSV saved: {csv_path}",
                flush=True,
            )


if __name__ == "__main__":
    main()
