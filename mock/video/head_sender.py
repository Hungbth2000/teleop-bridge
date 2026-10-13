
#!/usr/bin/env python3

import argparse
import json
import secrets
import struct
import sys
import time
from pathlib import Path

import zenoh

# Add the project root before importing mock.video.
sys.path.insert(
    0, str(Path(__file__).resolve().parents[2])
)

from mock.video.frame_protocol import (
    HEAD,
    fragment_frame,
)
from mock.video.frame_csv import VideoFrameCsv

ROBOT_PORT = 7448
VIDEO_TOPIC = "teleop/video/head/tx"


def connect():
    config = {
        "mode": "client",
        "connect": {
            "endpoints": [
                f"tcp/127.0.0.1:{ROBOT_PORT}"
            ]
        },
        "scouting": {
            "multicast": {"enabled": False}
        },
    }

    return zenoh.open(
        zenoh.Config.from_json5(json.dumps(config))
    )


def make_frame(frame_id, size):
    # Deterministic bytes so the receiver can
    # verify the reconstructed frame contents.
    prefix = struct.pack("!Q", frame_id)

    return (
        prefix +
        bytes([frame_id % 251]) * (size - 8)
    )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--fps",
        type=float,
        default=30.0,
    )

    parser.add_argument(
        "--frame-bytes",
        type=int,
        default=4000,
    )

    parser.add_argument(
        "--duration",
        type=float,
        default=30.0,
    )

    args = parser.parse_args()

    if args.fps <= 0:
        parser.error("--fps must be positive")

    if not 8 <= args.frame_bytes <= 1_000_000:
        parser.error(
            "--frame-bytes must be between 8 and 1000000"
        )

    if args.duration <= 0:
        parser.error("--duration must be positive")

    interval_ns = int(1e9 / args.fps)

    generated = 0
    fragments_sent = 0

    run_prefix = secrets.randbits(32)
    run_id = f"{run_prefix:08x}"

    print(f"[HEAD TX] run_id={run_id}", flush=True)

    print(
        f"[HEAD TX] {args.fps} fps, "
        f"{args.frame_bytes} bytes/frame, "
        f"duration={args.duration}s",
        flush=True,
    )

    with VideoFrameCsv("tx") as csv_log:
        with connect() as session:

            publisher = session.declare_publisher(
                VIDEO_TOPIC
            )

            # Allow the zenoh publication path to settle.
            time.sleep(0.5)

            start_ns = time.monotonic_ns()
            end_ns = start_ns + int(args.duration * 1e9)
            next_frame_ns = start_ns
            last_report_ns = start_ns

            while time.monotonic_ns() < end_ns:

                now_ns = time.monotonic_ns()

                if now_ns < next_frame_ns:
                    time.sleep(
                        (next_frame_ns - now_ns) / 1e9
                    )
                    continue

                frame_number = generated

                if frame_number >= (1 << 32):
                    raise RuntimeError("Frame number exhausted")

                frame_id = (run_prefix << 32) | frame_number

                capture_ns = time.monotonic_ns()

                frame = make_frame(
                    frame_id,
                    args.frame_bytes,
                )

                fragments = fragment_frame(
                    frame,
                    stream_id=HEAD,
                    frame_id=frame_id,
                    capture_ns=capture_ns,
                )

                
                for fragment in fragments:
                    publisher.put(fragment)
                    fragments_sent += 1

                csv_log.log(
                    run_id=run_id,
                    stream_id=HEAD,
                    frame_id=frame_id,
                    frame_number=frame_number,
                    capture_ns=capture_ns,
                    event_ns=time.monotonic_ns(),
                    frame_bytes=len(frame),
                    fragments=len(fragments),
                )

                generated += 1

                next_frame_ns += interval_ns

                # Skip elapsed capture slots rather than
                # trying to catch up with old frames.
                now_ns = time.monotonic_ns()

                if now_ns > next_frame_ns:
                    missed = (
                        (now_ns - next_frame_ns)
                        // interval_ns + 1
                    )
                    next_frame_ns += missed * interval_ns

                if now_ns - last_report_ns >= 1e9:
                    print(
                        f"[HEAD TX] generated={generated} "
                        f"fragments={fragments_sent}",
                        flush=True,
                    )

                    last_report_ns = now_ns

            print(
                f"[HEAD TX] DONE "
                f"run_id={run_id} "
                f"generated={generated} "
                f"fragments={fragments_sent}",
                flush=True,
            )


if __name__ == "__main__":
    main()
