#!/usr/bin/env python3

"""Test B3's native Zenoh configuration query locally."""

import json

import zenoh


PORT = 7447
QUERY_TOPIC = "teleop/robot/config"


def main():
    config = {
        "mode": "client",
        "connect": {
            "endpoints": [f"tcp/127.0.0.1:{PORT}"]
        },
        "scouting": {
            "multicast": {"enabled": False}
        },
    }

    with zenoh.open(
        zenoh.Config.from_json5(json.dumps(config))
    ) as session:

        print("[TEST] Sending native Zenoh query...", flush=True)

        replies = session.get(
            QUERY_TOPIC,
            timeout=3000,
        )

        successful = 0

        for reply in replies:
            if reply.ok is not None:
                payload = reply.ok.payload.to_bytes()
                data = json.loads(payload.decode("utf-8"))

                successful += 1

                print("[TEST] Reply:", data)

            else:
                print("[TEST] Query error:", reply.err)

        print(f"[TEST] Successful replies: {successful}")

        if successful != 1:
            raise SystemExit(
                "Expected exactly one successful reply"
            )


if __name__ == "__main__":
    main()
