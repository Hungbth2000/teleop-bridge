#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="teleop-robot"
OP_IF="veth-teleop-op"
RB_IF="veth-teleop-rb"

OP_IP="10.200.1.1/24"
RB_IP="10.200.1.2/24"

if [[ $EUID -ne 0 ]]; then
    echo "Please run with sudo."
    exit 1
fi

echo "[network] Setting up teleoperation network..."

# Create namespace if missing.
if ! ip netns list | awk '{print $1}' | grep -qx "$NAMESPACE"; then
    ip netns add "$NAMESPACE"
    echo "[network] Created namespace: $NAMESPACE"
fi

# Create veth pair if missing.
if ! ip link show "$OP_IF" &>/dev/null; then
    if ip netns exec "$NAMESPACE" ip link show "$RB_IF" &>/dev/null; then
        echo "[network] Inconsistent existing interface state."
        echo "[network] Please inspect the network manually."
        exit 1
    fi

    ip link add "$OP_IF" type veth peer name "$RB_IF"
    ip link set "$RB_IF" netns "$NAMESPACE"
    echo "[network] Created virtual Ethernet pair"
fi

# Verify that the robot endpoint exists.
if ! ip netns exec "$NAMESPACE" ip link show "$RB_IF" &>/dev/null; then
    echo "[network] Robot interface is missing."
    echo "[network] Please inspect the network manually."
    exit 1
fi

# Configure operator interface.
ip addr replace "$OP_IP" dev "$OP_IF"
ip link set "$OP_IF" up

# Configure robot interface.
ip netns exec "$NAMESPACE" \
    ip addr replace "$RB_IP" dev "$RB_IF"

ip netns exec "$NAMESPACE" \
    ip link set "$RB_IF" up

ip netns exec "$NAMESPACE" \
    ip link set lo up

echo "[network] Configuration complete."
echo
echo "[network] Operator:"
ip -br addr show "$OP_IF"

echo
echo "[network] Robot:"
ip netns exec "$NAMESPACE" \
    ip -br addr show "$RB_IF"

echo
echo "[network] Testing connectivity..."

if ip netns exec "$NAMESPACE" \
    ping -c 2 -W 1 10.200.1.1 >/dev/null; then
    echo "[network] Robot -> Operator: OK"
else
    echo "[network] Robot -> Operator: FAILED"
    exit 1
fi

if ping -c 2 -W 1 -I "$OP_IF" \
    10.200.1.2 >/dev/null; then
    echo "[network] Operator -> Robot: OK"
else
    echo "[network] Operator -> Robot: FAILED"
    exit 1
fi

echo
echo "[network] Ready."
