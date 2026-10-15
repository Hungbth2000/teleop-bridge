
#!/usr/bin/env python3

import argparse
import json
import re
import secrets
import sys
import threading
import time
from pathlib import Path

import zenoh

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mock.video.frame_csv import VideoFrameCsv
from mock.video.frame_protocol import HEAD, fragment_frame
from mock.video.head_h264_sender import read_access_units

ROBOT_PORT = 7448

VIDEO_TOPIC = "teleop/video/head/tx"
BANDWIDTH_TOPIC = "teleop/bridge/bandwidth"

NORMAL_BUDGET_BPS = 8_000_000

STATUS_TIMEOUT_SECONDS = 0.5
GOP = 30


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


def nal_types(access_unit):
    """Return the NAL types in an Annex B access unit."""
    markers = list(
        re.finditer(
            rb"\x00\x00(?:\x00)?\x01",
            access_unit,
        )
    )

    result = set()

    for marker in markers:
        offset = marker.end()

        if offset < len(access_unit):
            nal_header = access_unit[offset]
            result.add(nal_header & 0x1F)

    return result


def validate_representations(high, low):
    if len(high) != len(low):
        raise ValueError(
            "High and low streams have different "
            "frame counts"
        )

    for index in range(0, len(high), GOP):
        for name, frames in (
            ("high", high),
            ("low", low),
        ):
            types = nal_types(frames[index])

            # 7 = SPS, 8 = PPS, 5 = IDR slice
            if not {5, 7, 8}.issubset(types):
                raise ValueError(
                    f"{name} frame {index} is not "
                    "a self-contained IDR access unit "
                    "with SPS/PPS"
                )


class BandwidthStatus:
    def __init__(self):
        self.lock = threading.Lock()
        self.budget_bps = None
        self.last_update = None
        self.updates = 0
        self.bridge_monotonic_ns = None
        self.cycle_start_ns = None

    def snapshot(self):
        with self.lock:
            return {
                "budget_bps": self.budget_bps,
                "bridge_monotonic_ns": self.bridge_monotonic_ns,
                "cycle_start_ns": self.cycle_start_ns,
                "last_update": self.last_update,
            }

    def on_sample(self, sample):
        try:
            data = json.loads(
                sample.payload.to_bytes().decode(
                    "utf-8"
                )
            )

            bridge_ns = data.get("bridge_monotonic_ns")

            cycle_start_ns = data.get("cycle_start_ns")

            budget = int(data["budget_bps"])

            if budget <= 0:
                return

            with self.lock:
                self.budget_bps = budget
                self.last_update = time.monotonic()
                self.bridge_monotonic_ns = bridge_ns
                self.cycle_start_ns = cycle_start_ns
                self.updates += 1

        except Exception as error:
            print(
                f"[ADAPT] Invalid bandwidth status: "
                f"{error}",
                flush=True,
            )

    def desired_mode(self):
        with self.lock:
            budget = self.budget_bps
            updated = self.last_update

        if updated is None:
            return "low", "waiting for status"

        age = time.monotonic() - updated

        if age > STATUS_TIMEOUT_SECONDS:
            return "low", "status timeout"

        if budget >= NORMAL_BUDGET_BPS:
            return "high", "normal budget"

        return "low", "degraded budget"


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--high",
        type=Path,
        default=ROOT / "results" /
            "head_720p_75s_2mbps.h264",
    )
    parser.add_argument(
        "--low",
        type=Path,
        default=ROOT / "results" /
            "head_720p_75s_1200k.h264",
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

    high_frames = read_access_units(args.high)
    low_frames = read_access_units(args.low)

    validate_representations(
        high_frames,
        low_frames,
    )

    requested = round(
        args.fps * args.duration
    )

    if requested > len(high_frames):
        parser.error(
            f"Requested {requested} frames, "
            f"but files contain {len(high_frames)}"
        )

    run_prefix = secrets.randbits(32)
    run_id = f"{run_prefix:08x}"

    status = BandwidthStatus()
    interval_ns = int(1e9 / args.fps)

    current_mode = "low"
    switches = 0
    generated = 0
    fragments_sent = 0
    mode_counts = {
        "high": 0,
        "low": 0,
    }

    print(
        f"[ADAPT] Run ID: {run_id}",
        flush=True,
    )
    print(
        f"[ADAPT] Frames: {requested}",
        flush=True,
    )
    print(
        "[ADAPT] Waiting for bridge status...",
        flush=True,
    )

    with VideoFrameCsv("tx") as csv_log:
        with connect() as session:
            subscriber = session.declare_subscriber(
                BANDWIDTH_TOPIC,
                status.on_sample,
            )

            publisher = session.declare_publisher(
                VIDEO_TOPIC
            )

            # Give zenoh time to establish the
            # subscription and receive initial status.
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

                # Only change representation at
                # independently decodable IDR frames.
                if frame_number % GOP == 0:
                    if desired != current_mode:
                        current_mode = desired
                        switches += 1

                        print(
                            f"[ADAPT] SWITCH "
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
                    stream_id=HEAD,
                    frame_id=frame_id,
                    capture_ns=capture_ns,
                )

                for fragment in fragments:
                    publisher.put(fragment)
                    fragments_sent += 1

                bandwidth = status.snapshot()

                csv_log.log(
                    run_id=run_id,
                    stream_id=HEAD,
                    frame_id=frame_id,
                    frame_number=frame_number,
                    capture_ns=capture_ns,
                    event_ns=time.monotonic_ns(),
                    frame_bytes=len(frame),
                    fragments=len(fragments),
                    budget_bps=bandwidth["budget_bps"],
                    bridge_monotonic_ns=bandwidth["bridge_monotonic_ns"],
                    cycle_start_ns=bandwidth["cycle_start_ns"],
                )

                generated += 1
                mode_counts[current_mode] += 1

                if generated % 30 == 0:
                    desired, reason = (
                        status.desired_mode()
                    )

                    print(
                        f"[ADAPT] frames={generated} "
                        f"active={current_mode} "
                        f"requested={desired} "
                        f"reason={reason}",
                        flush=True,
                    )

            print(
                f"[ADAPT] DONE run_id={run_id} "
                f"frames={generated} "
                f"fragments={fragments_sent} "
                f"switches={switches}",
                flush=True,
            )

            print(
                f"[ADAPT] High frames: "
                f"{mode_counts['high']}",
                flush=True,
            )

            print(
                f"[ADAPT] Low frames: "
                f"{mode_counts['low']}",
                flush=True,
            )


if __name__ == "__main__":
    main()
