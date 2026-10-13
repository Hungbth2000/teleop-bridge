
#!/usr/bin/env python3

import json
import time
from datetime import datetime

import zenoh

TOPIC = "teleop/bridge/bandwidth"


def main():
    config = {
        "mode": "client",
        "connect": {
            "endpoints": ["tcp/127.0.0.1:7448"]
        },
        "scouting": {
            "multicast": {
                "enabled": False
            }
        },
    }

    print(
        "[BW MONITOR] Connecting to robot zenoh...",
        flush=True,
    )

    with zenoh.open(
        zenoh.Config.from_json5(
            json.dumps(config)
        )
    ) as session:

        last_budget = None
        message_count = 0
        last_report = time.monotonic()

        def on_status(sample):

            nonlocal last_budget, message_count, last_report

            message_count += 1

            now = time.monotonic()

            if now - last_report >= 5.0:
                elapsed = now - last_report
                rate = message_count / elapsed

                print(
                    f"[BW MONITOR] Status rate: "
                    f"{rate:.2f} messages/s",
                    flush=True,
                )

                message_count = 0
                last_report = now

            try:
                payload = json.loads(
                    sample.payload.to_bytes().decode(
                        "utf-8"
                    )
                )

                budget = payload["budget_bps"]
                phase = payload["phase"]

                timestamp = datetime.now().strftime(
                    "%H:%M:%S"
                )

                if budget != last_budget:
                    print(
                        f"[{timestamp}] "
                        f"Budget={budget / 1e6:.1f} Mbit/s "
                        f"Phase={phase}",
                        flush=True,
                    )
                    last_budget = budget

            except Exception as error:
                print(
                    f"[BW MONITOR] Invalid status: {error}",
                    flush=True,
                )

        subscriber = session.declare_subscriber(
            TOPIC,
            on_status,
        )

        print(
            f"[BW MONITOR] Subscribed to {TOPIC}",
            flush=True,
        )

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print(
                "\n[BW MONITOR] Stopped",
                flush=True,
            )


if __name__ == "__main__":
    main()
