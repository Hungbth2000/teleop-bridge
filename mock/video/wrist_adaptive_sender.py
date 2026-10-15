
#!/usr/bin/env python3

import argparse
import csv
import secrets
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mock.video.frame_protocol import (
    LEFT_WRIST,
    RIGHT_WRIST,
    fragment_frame,
)
from mock.video.head_h264_sender import read_access_units
from mock.video.head_adaptive_sender import (
    BANDWIDTH_TOPIC,
    BandwidthStatus,
    GOP,
    connect,
    validate_representations,
)

CAMERAS = {
    "left": {
        "id": LEFT_WRIST,
        "topic": "teleop/video/wrist_left/tx",
        "high": ROOT / "results" /
            "wrist_left_75s_400k.h264",
        "low": ROOT / "results" /
            "wrist_left_75s_250k.h264",
    },
    "right": {
        "id": RIGHT_WRIST,
        "topic": "teleop/video/wrist_right/tx",
        "high": ROOT / "results" /
            "wrist_right_75s_400k.h264",
        "low": ROOT / "results" /
            "wrist_right_75s_250k.h264",
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
    "budget_bps",
    "bridge_monotonic_ns",
    "cycle_start_ns",
]


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--camera",
        choices=["left", "right"],
        required=True,
    )

    parser.add_argument(
        "--high",
        type=Path,
        default=None,
    )

    parser.add_argument(
        "--low",
        type=Path,
        default=None,
    )

    parser.add_argument(
        "--fps",
        type=float,
        default=30.0,
    )

    parser.add_argument(
        "--duration",
        type=float,
        default=75.0,
    )

    args = parser.parse_args()

    if args.fps != 30.0:
        parser.error(
            "This test requires 30 fps and GOP 30"
        )

    if args.duration <= 0:
        parser.error("Duration must be positive")

    camera = CAMERAS[args.camera]

    high_path = args.high or camera["high"]
    low_path = args.low or camera["low"]

    for path in (high_path, low_path):
        if not path.is_file():
            parser.error(f"File not found: {path}")

    print(
        f"[WRIST ADAPT] Loading {args.camera} "
        "representations...",
        flush=True,
    )

    high_frames = read_access_units(high_path)
    low_frames = read_access_units(low_path)

    validate_representations(
        high_frames,
        low_frames,
    )

    requested = round(args.fps * args.duration)

    if requested > len(high_frames):
        parser.error(
            f"Requested {requested} frames, "
            f"but files contain {len(high_frames)}"
        )

    run_prefix = secrets.randbits(32)
    run_id = f"{run_prefix:08x}"

    csv_path = (
        ROOT / "results" /
        f"video_frames_tx_wrist_{args.camera}.csv"
    )

    csv_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    status = BandwidthStatus()

    interval_ns = int(1e9 / args.fps)

    current_mode = "low"

    switches = 0
    generated = 0
    fragments_sent = 0
    bytes_sent = 0

    mode_counts = {
        "high": 0,
        "low": 0,
    }

    print(
        f"[WRIST ADAPT] camera={args.camera} "
        f"run_id={run_id} "
        f"frames={requested}",
        flush=True,
    )

    print(
        "[WRIST ADAPT] Waiting for bridge status...",
        flush=True,
    )

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

            subscriber = session.declare_subscriber(
                BANDWIDTH_TOPIC,
                status.on_sample,
            )

            publisher = session.declare_publisher(
                camera["topic"]
            )

            # Allow initial bandwidth status to arrive.
            time.sleep(0.5)

            start_ns = time.monotonic_ns()

            for frame_number in range(requested):

                scheduled_ns = (
                    start_ns +
                    frame_number * interval_ns
                )

                remaining_ns = (
                    scheduled_ns -
                    time.monotonic_ns()
                )

                if remaining_ns > 0:
                    time.sleep(remaining_ns / 1e9)

                desired, reason = status.desired_mode()

                # A representation can only change at
                # a self-contained IDR access unit.
                if frame_number % GOP == 0:

                    if desired != current_mode:

                        current_mode = desired
                        switches += 1

                        print(
                            f"[WRIST ADAPT] SWITCH "
                            f"camera={args.camera} "
                            f"frame={frame_number} "
                            f"mode={current_mode} "
                            f"reason={reason}",
                            flush=True,
                        )

                if current_mode == "high":
                    frame = high_frames[frame_number]
                else:
                    frame = low_frames[frame_number]

                capture_ns = time.monotonic_ns()

                frame_id = (
                    (run_prefix << 32) |
                    frame_number
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

                bandwidth = status.snapshot()

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
                    "budget_bps": bandwidth["budget_bps"],
                    "bridge_monotonic_ns": bandwidth["bridge_monotonic_ns"],
                    "cycle_start_ns": bandwidth["cycle_start_ns"],
                })

                generated += 1
                mode_counts[current_mode] += 1

                if generated % 30 == 0:

                    csv_file.flush()

                    desired, reason = (
                        status.desired_mode()
                    )

                    print(
                        f"[WRIST ADAPT] "
                        f"camera={args.camera} "
                        f"frames={generated} "
                        f"active={current_mode} "
                        f"requested={desired} "
                        f"reason={reason}",
                        flush=True,
                    )

            csv_file.flush()

            print(
                f"[WRIST ADAPT] DONE "
                f"camera={args.camera} "
                f"run_id={run_id} "
                f"frames={generated} "
                f"fragments={fragments_sent} "
                f"fragment_bytes={bytes_sent} "
                f"switches={switches}",
                flush=True,
            )

            print(
                f"[WRIST ADAPT] High frames: "
                f"{mode_counts['high']}",
                flush=True,
            )

            print(
                f"[WRIST ADAPT] Low frames: "
                f"{mode_counts['low']}",
                flush=True,
            )

    print(
        f"[WRIST ADAPT] CSV saved: {csv_path}",
        flush=True,
    )


if __name__ == "__main__":
    main()
