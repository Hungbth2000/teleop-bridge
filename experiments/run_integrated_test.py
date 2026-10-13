
#!/usr/bin/env python3

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import zenoh

ROOT = Path(__file__).resolve().parents[1]

CAMERA_RUNNER = ROOT / "experiments/run_three_cameras.py"
CONTROL_TEST = ROOT / "experiments/run_control_latency.py"

BANDWIDTH_TOPIC = "teleop/bridge/bandwidth"

NORMAL_BPS = 8_000_000
DEGRADED_BPS = 2_000_000


class BudgetMonitor:
    def __init__(self):
        self.lock = threading.Lock()
        self.budget = None
        self.updated_at = None

    def on_sample(self, sample):
        try:
            data = json.loads(
                sample.payload.to_bytes().decode("utf-8")
            )
            budget = int(data["budget_bps"])

            with self.lock:
                self.budget = budget
                self.updated_at = time.monotonic()

        except (ValueError, KeyError, UnicodeDecodeError):
            pass

    def get(self):
        with self.lock:
            if (
                self.updated_at is None
                or time.monotonic() - self.updated_at > 0.5
            ):
                return None

            return self.budget


def connect():
    config = {
        "mode": "client",
        "connect": {
            "endpoints": ["tcp/127.0.0.1:7448"]
        },
        "scouting": {
            "multicast": {"enabled": False}
        },
    }

    return zenoh.open(
        zenoh.Config.from_json5(json.dumps(config))
    )


def run_control(phase):
    command = [
        sys.executable,
        str(CONTROL_TEST),
        "--phase", phase,
        "--trials", "2",
        "--interval", "0.1",
    ]

    print(
        f"[INTEGRATED] Starting {phase} E-stop tests",
        flush=True,
    )

    result = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
    )

    print(
        f"[INTEGRATED] {phase} test exit={result.returncode}",
        flush=True,
    )

    return result.returncode == 0


def main():
    monitor = BudgetMonitor()

    with connect() as session:
        subscriber = session.declare_subscriber(
            BANDWIDTH_TOPIC,
            monitor.on_sample,
        )

        camera_process = subprocess.Popen(
            [
                sys.executable,
                str(CAMERA_RUNNER),
                "--duration", "75",
            ],
            cwd=ROOT,
        )

        normal_done = False
        degraded_done = False
        previous_budget = None
        startup_time = time.monotonic()

        try:
            while camera_process.poll() is None:
                budget = monitor.get()

                # Wait for receiver initialization,
                # sender startup and initial video traffic.
                if time.monotonic() - startup_time < 7:
                    previous_budget = budget
                    time.sleep(0.1)
                    continue

                # Only launch a degraded test at the
                # start of a newly observed 2 Mbps phase.
                entered_degraded = (
                    budget == DEGRADED_BPS
                    and previous_budget == NORMAL_BPS
                )

                if (
                    not degraded_done
                    and entered_degraded
                ):
                    degraded_done = run_control("degraded")

                # Normal testing can begin whenever
                # a fresh normal status is observed.
                elif (
                    not normal_done
                    and budget == NORMAL_BPS
                ):
                    normal_done = run_control("normal")

                previous_budget = monitor.get()
                time.sleep(0.1)

        except KeyboardInterrupt:
            print("\n[INTEGRATED] Interrupted", flush=True)

        finally:
            if camera_process.poll() is None:
                camera_process.send_signal(2)

            try:
                camera_process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                camera_process.terminate()
                camera_process.wait()

        print("\n[INTEGRATED] Experiment finished")
        print(f"Normal test started: {normal_done}")
        print(f"Degraded test started: {degraded_done}")


if __name__ == "__main__":
    main()
