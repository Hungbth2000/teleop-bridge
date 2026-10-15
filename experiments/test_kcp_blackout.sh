#!/usr/bin/env bash
set -euo pipefail

cleanup() {
    sudo tc qdisc del dev veth-teleop-op clsact \
        2>/dev/null || true

    sudo ip netns exec teleop-robot \
        tc qdisc del dev veth-teleop-rb clsact \
        2>/dev/null || true
}

trap cleanup EXIT INT TERM

# Clear stale blackout filters first.
cleanup

echo "[TEST] Workload starting"

sudo -E "$PWD/.venv/bin/python" \
    experiments/run_three_cameras.py \
    --duration 15 \
    --robot-netns teleop-robot &

runner_pid=$!

sleep 5

echo "[TEST] Blackout START $(date --iso-8601=ns)"

sudo tc qdisc add dev veth-teleop-op clsact
sudo ip netns exec teleop-robot \
    tc qdisc add dev veth-teleop-rb clsact

sudo tc filter add dev veth-teleop-op \
    ingress protocol ip pref 10 flower action drop

sudo ip netns exec teleop-robot \
    tc filter add dev veth-teleop-rb \
    ingress protocol ip pref 10 flower action drop

sleep 0.5

cleanup

echo "[TEST] Blackout END $(date --iso-8601=ns)"

wait "$runner_pid"

echo "[TEST] Finished"
