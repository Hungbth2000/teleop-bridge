# Teleoperation Bridge — Measurement Record

## 1. Purpose

This document records experimental results from the teleoperation bridge coding challenge.

Raw logs and CSV files are stored under `results/final_validation/`.

Results are separated into preliminary validation, network-profile validation, and final acceptance tests.

## 2. Network validation

| Profile | Measured average RTT | Observed ICMP loss |
|---|---:|---:|
| Office LAN | 0.049 ms | 0% |
| Inter-city | 20.531 ms | 0.24% |
| Warehouse Wi-Fi | 92.19 ms | 3.65% |

The warehouse loss measurement includes deliberate connectivity blackouts.

## 3. Office LAN — 75-second hybrid tests

| Metric | TCP/UDP | QUIC/UDP | KCP/UDP |
|---|---:|---:|---:|
| Head frames received | 2250 | 2250 | 2250 |
| Left wrist frames received | 2191 | 2211 | 2214 |
| Right wrist frames received | 2190 | 2212 | 2211 |
| State updates received | 3850 | 3850 | 3850 |
| State-age p95 | 4.158 ms | 2.686 ms | 4.242 ms |
| Successful queries | 75/75 | 75/75 | 75/75 |

These measurements were collected before motion-reception latency logging was added.

They are preliminary functional benchmarks, not complete Task 2 acceptance results.

## 4. Motion-reception smoke tests

| Metric | Session 1 | Session 2 | Session 3 |
|---|---:|---:|---:|
| Commands received | 561 | 562 | 563 |
| Latency p50 | 1.902 ms | 1.858 ms | 1.576 ms |
| Latency p95 | 2.281 ms | 4.094 ms | 3.059 ms |
| Latency p99 | 2.712 ms | 4.847 ms | 4.471 ms |
| Stale at reception | 0 | 0 | 0 |

The sessions are not yet matched to verified transport and network-profile labels.

## 5. Bandwidth limiter implementation

Source: `bridge/include/rate_limiter.hpp`

The implemented token bucket uses:

- Normal budget: 8 Mbit/s.
- Degraded budget: 2 Mbit/s.
- Cycle duration: 60 seconds.
- Degraded interval: seconds 45–60.
- Maximum token accumulation: 4096 bytes.

The robot-side scheduler calls `pop_limited()` before transmitting queued messages.

Source: `bridge/include/csv_telemetry.hpp`

The bridge records per-traffic-category transmitted and received serialized bytes, estimated rates, queue drops, expirations, rejections, and send failures.

These are implementation facts, not proof that the physical network rate stays below the budget.

## 6. Outstanding acceptance tests

- Verify actual transmitted bandwidth against the configured budget.
- Verify at least 80% timely intact head-camera frames during the 2 Mbit/s interval.
- Measure repeated E-stop command-to-effect latency.
- Verify exactly-once and ordered reliable-command processing.
- Verify query timeout and duplicate-reply behavior.
- Measure 300 ms motion-watchdog behavior.
- Measure bridge-restart recovery on both endpoints.
- Generate the combined bandwidth, frame-latency, and motion-age timeline.

## 7. Interpretation

The current evidence demonstrates that the core bridge, traffic scheduling, transport alternatives, and network emulation are functioning.

The remaining tests are needed before claiming full compliance with the assignment.
