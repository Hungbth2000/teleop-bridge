
#!/usr/bin/env python3

import argparse
import json
import secrets
import sys
import time
from pathlib import Path

import zenoh

import csv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mock.video.frame_protocol import (
    LEFT_WRIST,
    RIGHT_WRIST,
    fragment_frame,
)
from mock.video.head_h264_sender import (
    read_access_units,
)


CAMERAS = {
    "left": {
        "id": LEFT_WRIST,
        "topic": "teleop/video/wrist_left/tx",
    },
    "right": {
        "id": RIGHT_WRIST,
        "topic": "teleop/video/wrist_right/tx",
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
            "endpoints": ["tcp/127.0.0.1:7448"]
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
        "--camera",
        choices=["left", "right"],
        required=True,
    )

    parser.add_argument(
        "--file",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--fps",
        type=float,
        default=30.0,
    )

    args = parser.parse_args()

    csv_path = (
        ROOT / "results" /
        f"video_frames_tx_wrist_{args.camera}.csv"
    )

    csv_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if args.fps <= 0:
        parser.error("FPS must be positive")

    if not args.file.is_file():
        parser.error(f"File not found: {args.file}")

    frames = read_access_units(args.file)
    camera = CAMERAS[args.camera]

    run_prefix = secrets.randbits(32)
    run_id = f"{run_prefix:08x}"

    interval_ns = int(1e9 / args.fps)

    fragments_sent = 0
    bytes_sent = 0

    print(
        f"[WRIST TX] camera={args.camera} "
        f"run_id={run_id} "
        f"frames={len(frames)}",
        flush=True,
    )
    
    # Append to preserve previous experimental runs.
    with csv_path.open(
        "a",
        newline="",
        encoding="utf-8",
    ) as csv_file:

        writer = csv.DictWriter(
            csv_file,
            fieldnames=CSV_FIELDS,
        )

        if csv_file.tell() == 0:
            writer.writeheader()

        with connect() as session:
            publisher = session.declare_publisher(
                camera["topic"]
            )

            time.sleep(0.5)
            start_ns = time.monotonic_ns()

            for frame_number, frame in enumerate(frames):
                target_ns = (
                    start_ns + frame_number * interval_ns
                )

                remaining_ns = (
                    target_ns - time.monotonic_ns()
                )

                if remaining_ns > 0:
                    time.sleep(remaining_ns / 1e9)

                capture_ns = time.monotonic_ns()

                frame_id = (
                    (run_prefix << 32) | frame_number
                )

                fragments = fragment_frame(
                    frame,
                    stream_id=camera["id"],
                    frame_id=frame_id,
                    capture_ns=capture_ns,
                )

                for fragment in fragments:
                    publisher.put(fragment)
                    fragments_sent += 1
                    bytes_sent += len(fragment)

                writer.writerow({
                    "run_id": run_id,
                    "stream_id": camera["id"],
                    "frame_id": frame_id,
                    "frame_number": frame_number,
                    "capture_ns": capture_ns,
                    "event_ns": time.monotonic_ns(),
                    "frame_bytes": len(frame),
                    "fragments": len(fragments),
                    "latency_ms": "",
                })

                if (frame_number + 1) % 30 == 0:
                    csv_file.flush()

                    print(
                        f"[WRIST TX] "
                        f"camera={args.camera} "
                        f"generated={frame_number + 1}",
                        flush=True,
                    )

            csv_file.flush()

            print(
                f"[WRIST TX] DONE "
                f"camera={args.camera} "
                f"run_id={run_id} "
                f"frames={len(frames)} "
                f"fragments={fragments_sent} "
                f"fragment_bytes={bytes_sent}",
                flush=True,
            )

    print(
        f"[WRIST TX] CSV saved: {csv_path}",
        flush=True,
    )



if __name__ == "__main__":
    main()
