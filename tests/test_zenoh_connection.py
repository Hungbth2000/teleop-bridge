
import argparse
import json
import time

import zenoh

PORTS = {
    "operator": 7447,
    "robot": 7448,
}

DEFAULT_KEY = "teleop/test/message"


def connect(site):
    config = {
        "mode": "client",
        "connect": {
            "endpoints": [f"tcp/127.0.0.1:{PORTS[site]}"]
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
        "--site",
        choices=["operator", "robot"],
        required=True,
        help="Select the local zenoh router"
    )

    parser.add_argument(
    "--key",
    default=DEFAULT_KEY,
    help="zenoh topic for publishing or subscribing"
    )
    parser.add_argument(
        "--mode", choices=["pub", "sub"], required=True
    )
    args = parser.parse_args()

    with connect(args.site) as session:
        print(f"Connected to {args.site} router", flush=True)

        if args.mode == "sub":
            def on_message(sample):
                print(
                    f"Received: {sample.payload.to_string()}",
                    flush=True
                )

            subscriber = session.declare_subscriber(
                args.key, on_message
            )
            print("Waiting for messages...", flush=True)

            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass

        else:
            publisher = session.declare_publisher(args.key)
            counter = 0

            try:
                while True:
                    message = f"{args.site}: message {counter}"
                    publisher.put(message)
                    print(f"Sent: {message}", flush=True)

                    counter += 1
                    time.sleep(1)
            except KeyboardInterrupt:
                pass


if __name__ == "__main__":
    main()
