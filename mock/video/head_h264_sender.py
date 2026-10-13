
#!/usr/bin/env python3

import argparse
import json
import re
import secrets
import sys
import time
from pathlib import Path

import zenoh

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mock.video.frame_csv import VideoFrameCsv
from mock.video.frame_protocol import (
    HEAD,
    MAX_FRAME_SIZE,
    fragment_frame,
)

ROBOT_PORT = 7448
VIDEO_TOPIC = "teleop/video/head/tx"

# H.264 Annex B: 3-byte or 4-byte start code,
# immediately followed by the AUD NAL header.
AUD_PATTERN = re.compile(
    rb"\x00\x00(?:\x00)?\x01\x09"
)


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


def read_access_units(path):
    """Extract H.264 access units using AUD boundaries.

    Requires an Annex B bitstream encoded with aud=1.
    Each returned access unit represents one video frame.
    """
    data = path.read_bytes()
    matches = list(AUD_PATTERN.finditer(data))

    if not matches:
        raise ValueError(
            "No H.264 AUD markers found. "
            "Encode using -x264-params aud=1"
        )

    # Any bytes before the first AUD are preserved
    # with the first access unit. Normally aud=1
    # places an AUD at the beginning.
    starts = [match.start() for match in matches]

    if starts[0] != 0:
        print(
            f"[H264 TX] Preserving {starts[0]} "
            "preamble bytes with first frame",
            flush=True,
        )

    frames = []

    for index, start in enumerate(starts):
        end = (
            starts[index + 1]
            if index + 1 < len(starts)
            else len(data)
        )

        if index == 0:
            start = 0

        frame = data[start:end]

        if not 0 < len(frame) <= MAX_FRAME_SIZE:
            raise ValueError(
                f"Invalid encoded frame size: {len(frame)}"
            )

        frames.append(frame)

    return frames


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--file",
        type=Path,
        default=ROOT / "results" /
            "head_720p_30fps_2mbps.h264",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=30.0,
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=30.0,
    )

    args = parser.parse_args()

    if args.fps <= 0 or args.duration <= 0:
        parser.error("FPS and duration must be positive")

    if not args.file.is_file():
        parser.error(f"File not found: {args.file}")

    frames = read_access_units(args.file)

    requested_frames = round(
        args.fps * args.duration
    )

    if len(frames) < requested_frames:
        parser.error(
            f"Only {len(frames)} encoded frames found; "
            f"{requested_frames} requested"
        )

    frames = frames[:requested_frames]

    run_prefix = secrets.randbits(32)
    run_id = f"{run_prefix:08x}"

    interval_ns = int(1e9 / args.fps)

    generated = 0
    fragments_sent = 0
    skipped_slots = 0

    encoded_bytes = sum(map(len, frames))
    largest_frame = max(map(len, frames))

    print(
        f"[H264 TX] run_id={run_id} "
        f"frames={len(frames)} "
        f"fps={args.fps}",
        flush=True,
    )

    print(
        f"[H264 TX] encoded_bytes={encoded_bytes} "
        f"largest_frame={largest_frame} bytes",
        flush=True,
    )

    with VideoFrameCsv("tx") as csv_log:
        with connect() as session:
            publisher = session.declare_publisher(
                VIDEO_TOPIC
            )

            time.sleep(0.5)

            start_ns = time.monotonic_ns()
            last_report_ns = start_ns

            for frame_number, frame in enumerate(frames):
                scheduled_ns = (
                    start_ns + frame_number * interval_ns
                )

                now_ns = time.monotonic_ns()

                if now_ns < scheduled_ns:
                    time.sleep(
                        (scheduled_ns - now_ns) / 1e9
                    )

                # Timestamp the actual frame release.
                # This excludes offline encoding time.
                capture_ns = time.monotonic_ns()

                frame_id = (
                    (run_prefix << 32) | frame_number
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
                now_ns = time.monotonic_ns()

                if now_ns - scheduled_ns > interval_ns:
                    skipped_slots += 1

                if now_ns - last_report_ns >= 1e9:
                    print(
                        f"[H264 TX] generated={generated} "
                        f"fragments={fragments_sent}",
                        flush=True,
                    )
                    last_report_ns = now_ns

            print(
                f"[H264 TX] DONE run_id={run_id} "
                f"generated={generated} "
                f"fragments={fragments_sent} "
                f"overrun_slots={skipped_slots}",
                flush=True,
            )


if __name__ == "__main__":
    main()
