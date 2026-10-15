# Task 2.2 — Fast Motion Commands and Safety Validation

## Test Setup

Transport: Hybrid TCP/UDP, using Zenoh routers and a Linux network namespace.

Normal workload: 75 seconds with concurrent head and wrist camera streams, motion commands, state updates, and query traffic.

Motion commands contain a sequence number, creation timestamp, and sender session ID. B3 validates command freshness and ordering before applying the simulated motion state.

## Motion Command Latency

B3 received and applied 7,561 commands during the normal workload.

| Metric | Result |
|---|---:|
| Received commands | 7,561 |
| Applied commands | 7,561 |
| p50 age | 1.997 ms |
| p95 age | 4.300 ms |
| p99 age | 4.779 ms |
| Maximum age | 9.974 ms |
| Detected safety violations | 0 |

Command age is calculated from the A1 creation timestamp to the B3 reception timestamp.

These figures cover commands received at B3. They do not independently measure commands lost before reception.

## Safety Validation

| Scenario | Result | Outcome |
|---|---|---|
| Stale command | Age 201.329 ms; rejected_stale | PASS |
| Duplicate sequence | Sequence 100; rejected_sequence | PASS |
| Reordered sequence | Sequence 99; rejected_sequence | PASS |
| Watchdog timeout | Motion stopped after 282.170 ms | PASS |

B3 rejects motion commands exceeding the 150 ms age limit or having a non-increasing sequence number within a sender session.

The rejected test commands had empty application timestamps.

The dedicated watchdog test confirmed that B3 set its simulated moving state to false within 300 ms of the last accepted motion command.

## Evidence

### Normal Workload

- [Motion reception and application decisions](../evidence/motion_rx.csv)
- [B3 controller log](../evidence/b3_controller.log)
- [Concurrent workload logs](../evidence/three_camera_logs/)

### Fault-Injection Tests

- [Stale-command injection log](../safety_tests/stale/injection.log)
- [Stale-command result](../safety_tests/stale/stale_result.csv)
- [Sequence-test injection log](../safety_tests/duplicate_reordered/injection.log)
- [Duplicate and reordered results](../safety_tests/duplicate_reordered/sequence_results.csv)
- [Watchdog controller log](../safety_tests/watchdog/b3_watchdog.log)
- [Watchdog summary](../safety_tests/watchdog/watchdog_summary.json)

## Conclusion

The measured command-age percentiles remained low during the concurrent workload.

The targeted tests confirmed rejection of stale, duplicate, and reordered commands. The dedicated watchdog test also met the 300 ms stop deadline.

No safety violations were detected in the normal-workload analysis or the tested fault-injection cases.

The watchdog result is based on the simulated B3 controller's motion state, not physical actuator measurements.
