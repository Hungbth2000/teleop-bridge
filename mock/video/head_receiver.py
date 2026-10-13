
#!/usr/bin/env python3

import json
import struct
import threading
import time

import zenoh

from frame_protocol import (
    HEAD,
    FrameReassembler,
)

OPERATOR_PORT = 7447
VIDEO_TOPIC = "teleop/video/head/rx"


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
    reassembler = FrameReassembler()

    lock = threading.Lock()

    valid_frames = 0
    corrupt_frames = 0
    last_latency_ms = 0.0
    last_frame_id = -1

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

            expected = (
                struct.pack("!Q", frame_id)
                + bytes([frame_id % 251])
                * (len(data) - 8)
            )

            if data != expected:
                corrupt_frames += 1
                return

            valid_frames += 1
            last_latency_ms = result.latency_ms
            last_frame_id = frame_id

    print(
        "[HEAD RX] Waiting for video fragments...",
        flush=True,
    )

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


if __name__ == "__main__":
    main()
