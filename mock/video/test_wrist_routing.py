
#!/usr/bin/env python3

import argparse
import json
import sys
import time
from pathlib import Path

import zenoh

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mock.video.frame_protocol import (
    LEFT_WRIST,
    RIGHT_WRIST,
    fragment_frame,
)


def connect(port):
    config = {
        "mode": "client",
        "connect": {
            "endpoints": [
                f"tcp/127.0.0.1:{port}"
            ]
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


STREAMS = {
    "left": {
        "id": LEFT_WRIST,
        "tx": "teleop/video/wrist_left/tx",
        "rx": "teleop/video/wrist_left/rx",
    },
    "right": {
        "id": RIGHT_WRIST,
        "tx": "teleop/video/wrist_right/tx",
        "rx": "teleop/video/wrist_right/rx",
    },
}


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--role",
        choices=["tx", "rx"],
        required=True,
    )

    args = parser.parse_args()

    if args.role == "rx":
        with connect(7447) as session:

            subscribers = []

            for name, stream in STREAMS.items():

                def on_sample(sample, camera=name):
                    payload = sample.payload.to_bytes()

                    print(
                        f"[WRIST RX] camera={camera} "
                        f"bytes={len(payload)}",
                        flush=True,
                    )

                subscriber = session.declare_subscriber(
                    stream["rx"],
                    on_sample,
                )

                subscribers.append(subscriber)

            print(
                "[WRIST RX] Waiting for fragments...",
                flush=True,
            )

            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass

    else:
        with connect(7448) as session:

            # Allow discovery before publication.
            time.sleep(1)

            for name, stream in STREAMS.items():
                payload = (
                    f"wrist-routing-test-{name}"
                ).encode()

                fragments = fragment_frame(
                    payload,
                    stream_id=stream["id"],
                    frame_id=1,
                    capture_ns=time.monotonic_ns(),
                )

                for fragment in fragments:
                    session.put(
                        stream["tx"],
                        fragment,
                    )

                print(
                    f"[WRIST TX] camera={name} "
                    f"fragments={len(fragments)}",
                    flush=True,
                )

            time.sleep(1)


if __name__ == "__main__":
    main()
