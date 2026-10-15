
#!/usr/bin/env python3

"""Inter-city WAN network impairment profile."""

import argparse
import signal
import subprocess
import time


OP_INTERFACE = "veth-teleop-op"
ROBOT_INTERFACE = "veth-teleop-rb"


def run(*args):
    subprocess.run(args, check=True)


def apply_profile(namespace):
    settings = [
        "root",
        "netem",
        "delay", "10ms", "2ms",
        "loss", "0.1%",
    ]

    run(
        "tc", "qdisc", "replace",
        "dev", OP_INTERFACE,
        *settings,
    )

    run(
        "ip", "netns", "exec", namespace,
        "tc", "qdisc", "replace",
        "dev", ROBOT_INTERFACE,
        *settings,
    )

    print(
        "[NETWORK] Inter-city WAN profile active",
        flush=True,
    )
    print(
        "[NETWORK] Delay: 10ms +/- 2ms per direction (target RTT ~20ms)",
        flush=True,
    )
    print(
        "[NETWORK] Loss: 0.1% per direction",
        flush=True,
    )


def cleanup(namespace):
    subprocess.run(
        [
            "tc", "qdisc", "del",
            "dev", OP_INTERFACE, "root",
        ],
        check=False,
        stderr=subprocess.DEVNULL,
    )

    subprocess.run(
        [
            "ip", "netns", "exec", namespace,
            "tc", "qdisc", "del",
            "dev", ROBOT_INTERFACE, "root",
        ],
        check=False,
        stderr=subprocess.DEVNULL,
    )

    print(
        "[NETWORK] Inter-city profile removed",
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--namespace",
        default="teleop-robot",
    )
    args = parser.parse_args()

    # Only use this script with our isolated test interfaces.
    try:
        apply_profile(args.namespace)

        print(
            "[NETWORK] Press Ctrl+C to stop",
            flush=True,
        )

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        pass

    finally:
        cleanup(args.namespace)


if __name__ == "__main__":
    main()
