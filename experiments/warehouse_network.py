#!/usr/bin/env python3

import argparse
import signal
import subprocess
import time


OPERATOR_INTERFACE = "veth-teleop-op"
ROBOT_INTERFACE = "veth-teleop-rb"


def run_tc(command):
    subprocess.run(
        command,
        check=True,
    )


def apply_normal_delay(namespace):
    netem_settings = [
        "root", "netem",
        "delay", "45ms", "25ms",
        "loss", "gemodel",
        "0.2%", "20%", "100%", "0%",
    ]

    run_tc([
        "tc", "qdisc", "replace",
        "dev", OPERATOR_INTERFACE,
        *netem_settings,
    ])

    run_tc([
        "ip", "netns", "exec", namespace,
        "tc", "qdisc", "replace",
        "dev", ROBOT_INTERFACE,
        *netem_settings,
    ])

    print(
        "[NETWORK] Normal Wi-Fi delay and bursty loss applied",
        flush=True,
    )


def cleanup(namespace):
    commands = [
        [
            "tc", "qdisc", "del",
            "dev", OPERATOR_INTERFACE, "clsact",
        ],
        [
            "ip", "netns", "exec", namespace,
            "tc", "qdisc", "del",
            "dev", ROBOT_INTERFACE, "clsact",
        ],
        [
            "tc", "qdisc", "del",
            "dev", OPERATOR_INTERFACE, "root",
        ],
        [
            "ip", "netns", "exec", namespace,
            "tc", "qdisc", "del",
            "dev", ROBOT_INTERFACE, "root",
        ],
    ]

    for command in commands:
        subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    try:
        print("[NETWORK] Impairments removed", flush=True)
    except BrokenPipeError:
        pass

def interface_command(namespace, robot, *args):
    if robot:
        return [
            "ip", "netns", "exec", namespace,
            "tc", *args,
        ]

    return ["tc", *args]


def enable_blackout(namespace):
    interfaces = [
        (False, OPERATOR_INTERFACE),
        (True, ROBOT_INTERFACE),
    ]

    for robot, interface in interfaces:
        run_tc(interface_command(
            namespace, robot,
            "qdisc", "add",
            "dev", interface, "clsact",
        ))

        run_tc(interface_command(
            namespace, robot,
            "filter", "add",
            "dev", interface,
            "ingress",
            "protocol", "ip",
            "pref", "10",
            "flower",
            "action", "drop",
        ))

    print(
        f"[NETWORK] Blackout START "
        f"monotonic={time.monotonic():.6f}",
        flush=True,
    )

def disable_blackout(namespace):
    for robot, interface in [
        (False, OPERATOR_INTERFACE),
        (True, ROBOT_INTERFACE),
    ]:
        subprocess.run(
            interface_command(
                namespace, robot,
                "qdisc", "del",
                "dev", interface, "clsact",
            ),
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    print(
        f"[NETWORK] Blackout END "
        f"monotonic={time.monotonic():.6f}",
        flush=True,
    )

def apply_spike_delay(namespace):
    netem_settings = [
        "root", "netem",
        "delay", "130ms", "10ms",
        "loss", "gemodel",
        "0.2%", "20%", "100%", "0%",
    ]

    run_tc([
        "tc", "qdisc", "replace",
        "dev", OPERATOR_INTERFACE,
        *netem_settings,
    ])

    run_tc([
        "ip", "netns", "exec", namespace,
        "tc", "qdisc", "replace",
        "dev", ROBOT_INTERFACE,
        *netem_settings,
    ])

    print(
        f"[NETWORK] Latency spike START "
        f"monotonic={time.monotonic():.6f}",
        flush=True,
    )

def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--namespace",
        default="teleop-robot",
    )

    args = parser.parse_args()

    if subprocess.run(
        ["id", "-u"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip() != "0":
        parser.error("Run this controller with sudo")

    try:
        apply_normal_delay(args.namespace)

        print(
            "[NETWORK] Warehouse profile active",
            flush=True,
        )
        print(
            "[NETWORK] Blackout every 30 seconds",
            flush=True,
        )

        next_blackout = time.monotonic() + 30.0
        next_spike = time.monotonic() + 45.0

        while True:
            now = time.monotonic()

            if now >= next_blackout:
                try:
                    enable_blackout(args.namespace)
                    time.sleep(0.5)
                finally:
                    disable_blackout(args.namespace)

                next_blackout += 30.0

            elif now >= next_spike:
                try:
                    apply_spike_delay(args.namespace)
                    time.sleep(0.2)
                finally:
                    apply_normal_delay(args.namespace)

                print(
                    f"[NETWORK] Latency spike END "
                    f"monotonic={time.monotonic():.6f}",
                    flush=True,
                )

                next_spike += 60.0

            else:
                time.sleep(0.05)

    except KeyboardInterrupt:
        print("\n[NETWORK] Stopping", flush=True)

    finally:
        try:
            cleanup(args.namespace)
        except BrokenPipeError:
            pass


if __name__ == "__main__":
    main()
