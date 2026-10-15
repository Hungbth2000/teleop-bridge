## Task 2 — Build and Measure

### 2.1 Camera Streaming: Good-Frame Rate and Latency

**Objective**

Evaluate whether the C++ bridge can deliver video from all three robot cameras to the operator within the required 200 ms deadline while sharing a limited outbound bandwidth budget.

The primary acceptance requirement is that **at least 80% of head-camera frames must arrive intact within 200 ms when the robot-side bandwidth budget is 2 Mbit/s**.

#### Test Setup

The experiment was performed on a single Linux (WSL2) machine using two network environments: the operator side in the default network namespace and the robot side in the `teleop-robot` namespace. Each side communicates through its local Zenoh router.

The bridge uses a hybrid transport configuration:

- **UDP:** Real-time video, motion commands, and robot state.
- **TCP:** Reliable control commands and request/reply traffic.
- **Robot outbound bandwidth:** 8 Mbit/s normally, reduced to 2 Mbit/s for 15 seconds every 60 seconds.
- **Test duration:** 75 seconds.
- **Video streams:** One 1280×720 head camera and two 640×360 wrist cameras, all operating at 30 fps.

All three cameras streamed simultaneously while the motion, state, and query workloads were active.

#### Measurement Method

Each camera produces deterministic prerecorded H.264 video and attaches a unique frame ID and a monotonic capture timestamp to every encoded access unit.

The receiver performs the following operations:

1. Reassembles video fragments received through the bridge.
2. Verifies the reconstructed encoded frame's size and CRC32 checksum.
3. Decodes the H.264 access unit using PyAV.
4. Checks that a decoded image with the expected dimensions is produced.
5. Records the time when the decoded image becomes available to A2.

Frame latency is calculated as:

`latency_ms = (decoded_ns - capture_ns) / 1,000,000`

A frame is counted as good when it is successfully reconstructed, passes the encoded-data integrity check, produces a decoded image, and has a capture-to-decode latency of no more than 200 ms.

The good-frame rate is:

`good_frame_rate = (good_decoded_frames / total_captured_frames) × 100%`

Missing frames and frames exceeding the deadline are counted as unsuccessful.

To distinguish normal and degraded bandwidth operation, the robot bridge publishes its bandwidth-cycle start timestamp. Each camera records this timestamp alongside the frame capture time.

The bandwidth phase is calculated as:

`phase_s = ((capture_ns - cycle_start_ns) / 1e9) % 60`

- `0 ≤ phase_s < 45`: Normal phase, 8 Mbit/s.
- `45 ≤ phase_s < 60`: Degraded phase, 2 Mbit/s.

This allows the analysis to classify frames by the configured bandwidth at their capture time rather than relying on periodically sampled telemetry.

#### Results — Good-Frame Rate

| Camera | Bandwidth | Captured | Good frames | Good-frame rate | p95 latency |
|---|---|---:|---:|---:|---:|
| Head | 8 Mbit/s | 1,453 | 1,453 | 100.00% | 13.364 ms |
| Head | 2 Mbit/s | 797 | 797 | **100.00%** | 48.074 ms |
| Left wrist | 8 Mbit/s | 1,451 | 1,451 | 100.00% | 6.489 ms |
| Left wrist | 2 Mbit/s | 799 | 774 | 96.87% | 71.458 ms |
| Right wrist | 8 Mbit/s | 1,451 | 1,451 | 100.00% | 6.330 ms |
| Right wrist | 2 Mbit/s | 799 | 773 | 96.75% | 64.240 ms |

**Overall results across the 75-second experiment:**

| Camera | Captured | Good frames | Missing/unsuccessful | Good-frame rate | Overall p95 |
|---|---:|---:|---:|---:|---:|
| Head | 2,250 | 2,250 | 0 | 100.00% | 25.442 ms |
| Left wrist | 2,250 | 2,225 | 25 | 98.89% | 10.828 ms |
| Right wrist | 2,250 | 2,224 | 26 | 98.84% | 19.172 ms |

The 75-second recording spans portions of more than one degraded interval, resulting in approximately 800 captured frames per camera classified under the 2 Mbit/s budget.

#### Observations

The head camera achieved a **100% good-frame rate during the degraded 2 Mbit/s phase**, exceeding the required 80% threshold.

Reducing the bandwidth budget increased the measured capture-to-decode latency. For the head camera, p95 latency increased from 13.364 ms at 8 Mbit/s to 48.074 ms at 2 Mbit/s.

Both wrist cameras also maintained good-frame rates above 96% during the degraded phase. However, 25 left-wrist frames and 26 right-wrist frames were unsuccessful during this interval.

The results are consistent with the bridge's traffic prioritization, which favors head-camera video over wrist-camera video. The measurements do not independently establish the cause of every missing wrist frame.

The robot bridge telemetry also showed lower serialized-video transmission rates during the degraded phase, consistent with bandwidth adaptation and rate limiting. A separate network-byte accounting test is needed to establish strict compliance with the total outbound bandwidth budget.

#### Acceptance Result

**PASS — Head-camera good-frame rate at 2 Mbit/s**

- Required: at least 80% of captured head-camera frames delivered intact within 200 ms.
- Measured: **797 / 797 decoded frames within 200 ms (100%)**.
- Measured p95 capture-to-decode latency: **48.074 ms**.

The result establishes compliance with the timing and encoded-data integrity criteria in this headless test environment.

The measurement endpoint is decoded-frame readiness at A2 rather than physical monitor presentation. CRC32 verifies the reconstructed encoded data, and PyAV verifies successful decoding and the expected image dimensions. Pixel-by-pixel comparison against a decoded reference image has not yet been implemented.

#### Reproduction

With both Zenoh routers and the operator/robot C++ bridges running in `hybrid` transport mode:

```bash
sudo -E .venv/bin/python experiments/run_three_cameras.py \
  --duration 75 \
  --robot-netns teleop-robot
```

Archive the generated sender, receiver, decoder, and bridge telemetry CSV files before starting another experiment.

To reproduce the analysis from the archived evidence:

```bash
python experiments/analyze_phase_good_frames.py \
  --evidence results/task2/good_frames_tcp_udp/good_frame_evidence \
  --report results/task2/good_frames_tcp_udp/good_frame_report
```

#### Evidence and Reports

Raw evidence:

`results/task2/good_frames_tcp_udp/good_frame_evidence/`

- `video_frames_tx.csv` and `video_frames_rx.csv` — Head-camera capture and validated-reassembly records.
- `video_frames_tx_wrist_left.csv` and `video_frames_rx_wrist_left.csv` — Left-wrist records.
- `video_frames_tx_wrist_right.csv` and `video_frames_rx_wrist_right.csv` — Right-wrist records.
- `decoded_frames_head.csv` — Head-camera capture-to-decode measurements.
- `decoded_frames_left.csv` — Left-wrist capture-to-decode measurements.
- `decoded_frames_right.csv` — Right-wrist capture-to-decode measurements.
- `telemetry_robot_hybrid.csv` — Robot bridge traffic counters, observed rates, and configured bandwidth budget.
- `three_camera_logs/` — Experiment process logs.

Generated analysis:

`results/task2/good_frames_tcp_udp/good_frame_report/`

- `frame_classification.csv` — Frame-level classification by camera and bandwidth phase.
- `summary.csv` — Aggregated good-frame and latency measurements.
- `summary.json` — Machine-readable results.
- `report.md` — Generated experiment report.

The analysis is implemented in `experiments/analyze_phase_good_frames.py`.

### 2.2 Fast Motion Commands: Latency and Safety Validation

**Objective**

Evaluate whether the bridge can deliver motion commands from the operator (A1) to the robot controller (B3) with low latency while maintaining the required safety behavior.

The main requirements are:

- Measure command age at B3 and report p50, p95, and p99.
- Reject any motion command older than 150 ms.
- Never apply a duplicate or out-of-order motion command.
- Stop the robot within 300 ms if no fresh motion command arrives.
- Report zero safety-rule violations.

In addition to measuring command latency during normal operation, dedicated fault-injection tests were performed to verify that B3 correctly rejects invalid commands.

#### Test Setup

The experiment used the same WSL2 environment and hybrid TCP/UDP bridge configuration as Section 2.1.

Motion commands were generated by `mock/operator/a1_commands.py` at 100 Hz and transmitted from the operator-side Zenoh router to B3 through the C++ bridge using UDP.

Each motion command contains:

- An 8-byte sequence number.
- An 8-byte monotonic creation timestamp.
- An 84-byte motion payload, including the requested velocity and sender session ID.

The total application payload is 100 bytes.

The main measurement ran for 75 seconds with all three camera streams, robot state updates, and request/reply traffic active simultaneously. This allowed command latency to be evaluated under concurrent system load rather than in isolation.

The robot-side bandwidth budget also cycled between 8 Mbit/s and 2 Mbit/s during the experiment. However, the limiter applies to robot-to-operator traffic, while motion commands travel from operator to robot. Therefore, the results demonstrate motion performance under concurrent workload conditions, not direct enforcement of a 2 Mbit/s limit on the motion-command direction.

#### Measurement Method

B3 records the following information for each received, valid-size motion command:

- `session_id`: Identifies the sending A1 process.
- `sequence`: Command sequence number.
- `created_ns`: Monotonic timestamp when A1 created the command.
- `received_ns`: Monotonic timestamp when B3 received it.
- `latency_ms`: Command age at reception.
- `stale_at_reception`: Whether the command exceeded the freshness limit or had a negative age.
- `decision`: Whether the command was applied or rejected.
- `applied_ns`: Timestamp when the controller updated its simulated motion state; empty for rejected commands.

Command age is calculated as:

`command_age_ms = (received_ns - created_ns) / 1,000,000`

The p50, p95, and p99 values are calculated from the ages of commands recorded as `applied`.

B3 performs the following safety checks before applying motion:

1. **Freshness:** Reject commands with negative age or age greater than 150 ms.
2. **Session validity:** Reject commands from retired sender sessions or unauthorized session handovers.
3. **Sequence ordering:** Reject commands whose sequence number is less than or equal to the last accepted sequence number within the active session.
4. **E-stop state:** Prevent motion application while E-stop is latched.
5. **Watchdog:** Stop simulated motion when no fresh accepted motion command has arrived for approximately 280 ms, providing margin before the 300 ms deadline.

The individual command decisions are logged in `results/motion_rx.csv` and archived with the experiment evidence.

#### Results — Motion Command Latency

During the 75-second concurrent workload, B3 recorded 7,561 motion commands.

| Metric | Measured result |
|---|---:|
| Received commands | 7,561 |
| Applied commands | 7,561 |
| Rejected commands | 0 |
| Command age p50 | **1.997 ms** |
| Command age p95 | **4.300 ms** |
| Command age p99 | **4.779 ms** |
| Maximum command age | 9.974 ms |
| Detected safety violations | **0** |

All 7,561 commands received during this run were applied successfully.

The p99 command age was approximately 4.8 ms, while the maximum observed age was below 10 ms. These results show that command delivery remained responsive despite the concurrent camera, state, and query traffic.

No stale, duplicate, or reordered command applications were detected in the recorded normal-workload data.

The analysis checked command freshness, increasing sequence numbers within each sender session, and the presence and ordering of application timestamps.

**The reported 7,561 commands are those received at B3.** The test does not independently establish that every command originally transmitted by A1 was delivered.

#### Safety Validation — Stale Commands

A separate fault-injection test was performed using `experiments/test_stale_motion.py`.

The test generates a motion command with a creation timestamp deliberately set approximately 200 ms in the past:

`created_ns = time.monotonic_ns() - 200_000_000`

The command is transmitted through the normal operator-side Zenoh router and bridge path.

**Measured result:**

| Property | Result |
|---|---|
| Command sequence | 0 |
| Measured age at B3 | **201.329 ms** |
| Maximum permitted age | 150 ms |
| B3 decision | `rejected_stale` |
| Application timestamp | Empty |
| Result | **PASS** |

B3 received the command but rejected it because its age exceeded the configured threshold.

The empty application timestamp confirms that the controller recorded no motion application for this packet.

**Evidence:**

- [Stale-command injection log](../results/task2/fast_commands_tcp_udp/safety_tests/stale/injection.log)
- [Stale-command reception and rejection record](../results/task2/fast_commands_tcp_udp/safety_tests/stale/stale_result.csv)
- Test implementation: `experiments/test_stale_motion.py`

#### Safety Validation — Duplicate and Reordered Commands

The second fault-injection test verified that B3 does not apply duplicate or older sequence numbers.

A test sender published three commands using the same session ID:

1. Sequence 100: A valid command.
2. Sequence 100: A duplicate of the already accepted sequence number.
3. Sequence 99: An older, reordered command.

Each packet was created with a fresh monotonic timestamp so that sequence validation could be evaluated independently of stale-command rejection.

**Measured results:**

| Test | Sequence | Age at B3 | Controller decision | Result |
|---|---:|---:|---|---|
| Valid command | 100 | 2.470 ms | `applied` | PASS |
| Duplicate command | 100 | 2.516 ms | `rejected_sequence` | PASS |
| Reordered command | 99 | 1.640 ms | `rejected_sequence` | PASS |

B3 accepted sequence 100 once and rejected both subsequent invalid commands.

Neither rejected command received an application timestamp.

This demonstrates that the controller's sequence-number validation prevented duplicate and out-of-order commands from being applied in the tested scenario.

**Evidence:**

- [Sequence-test injection log](../results/task2/fast_commands_tcp_udp/safety_tests/duplicate_reordered/injection.log)
- [Sequence-test results](../results/task2/fast_commands_tcp_udp/safety_tests/duplicate_reordered/sequence_results.csv)
- [Test session identifier](../results/task2/fast_commands_tcp_udp/safety_tests/duplicate_reordered/session_id.txt)
- Test implementation: `experiments/test_motion_sequence.py`

#### Safety Validation — Motion Watchdog

The final safety test evaluated whether B3 stops simulated robot motion when fresh motion commands are interrupted.

B3 uses a watchdog threshold of 280 ms instead of the maximum permitted 300 ms to leave a small margin for polling and operating-system scheduling.

The test procedure was:

1. Start B3 with watchdog event logging enabled.
2. Start the A1 motion sender at 100 Hz.
3. Allow motion commands to arrive for approximately five seconds.
4. Stop A1 to simulate a loss of fresh motion commands.
5. Measure the elapsed time between the last accepted motion command and B3 setting `robot_moving=False`.

The elapsed watchdog time is calculated as:

`watchdog_elapsed_ms = (stop_ns - last_motion_ns) / 1,000,000`

**Measured result:**

| Property | Result |
|---|---:|
| Configured watchdog threshold | 280 ms |
| Required maximum stop time | 300 ms |
| Recorded watchdog events | 1 |
| Measured stop time | **282.170 ms** |
| Margin before deadline | 17.830 ms |
| Simulated robot state after timeout | `moving=False` |
| Result | **PASS** |

The recorded event confirms that B3 stopped simulated motion within the required 300 ms after the last accepted motion command.

The watchdog fired slightly later than its configured 280 ms threshold due to polling and execution scheduling, but remained within the safety deadline.

This test measures the simulated controller state, not physical motor stopping time.

**Evidence:**

- [A1 motion sender log](../results/task2/fast_commands_tcp_udp/safety_tests/watchdog/a1_motion.log)
- [B3 watchdog event log](../results/task2/fast_commands_tcp_udp/safety_tests/watchdog/b3_watchdog.log)
- [Watchdog measurement summary](../results/task2/fast_commands_tcp_udp/safety_tests/watchdog/watchdog_summary.json)

#### Overall Safety and Latency Results

| Requirement | Measured evidence | Status |
|---|---|---|
| Report command age p50/p95/p99 | 1.997 / 4.300 / 4.779 ms | Measured |
| Reject commands older than 150 ms | 201.329 ms command rejected | PASS |
| Reject duplicate commands | Repeated sequence 100 rejected | PASS |
| Reject reordered commands | Sequence 99 rejected after 100 | PASS |
| Stop when no fresh command arrives for 300 ms | Stop after 282.170 ms | PASS |
| Zero safety violations | 0 detected in 7,561 normal-workload received commands; targeted rejection tests passed | PASS for tested cases |

#### Observations

The motion-command path maintained low latency during the concurrent workload. Even at the 99th percentile, commands reached B3 in less than 5 ms.

The explicit freshness and sequence checks provide an additional safety layer beyond transport delivery. A delayed command cannot be applied simply because it eventually arrives, and repeated sequence numbers cannot cause the same motion update to be applied twice.

The watchdog provides protection against an interrupted command stream. In the dedicated test, the controller stopped simulated motion after 282.170 ms, satisfying the required 300 ms limit.

The results demonstrate correct behavior for the tested scenarios. The normal-workload analysis found no unsafe applications, while deliberate fault injection confirmed that stale, duplicate, and reordered commands were rejected.

#### Acceptance Result

**PASS — Fast-motion latency measurement and tested safety requirements**

- Command-age percentiles were measured under concurrent system load.
- No safety violations were detected in the recorded 75-second workload.
- The injected stale command was rejected.
- Duplicate and reordered commands were rejected without application.
- The watchdog stopped simulated motion within the 300 ms deadline.

The measurement uses synchronized monotonic timestamps within the same WSL2 Linux kernel. Results are application-level measurements in the test environment and do not establish equivalent performance on geographically separated physical machines.

The safety verdict is limited to the recorded commands and tested fault scenarios. It is not an exhaustive proof against all possible faults.

#### Reproduction

**Normal workload**

Start the operator and robot Zenoh routers and both C++ bridges in hybrid TCP/UDP mode. Start B3 in the robot namespace.

Then run:

```bash
sudo -E .venv/bin/python experiments/run_three_cameras.py \
  --duration 75 \
  --robot-netns teleop-robot
```

B3 records the command reception and application decisions in:

`results/motion_rx.csv`

Archive this file before conducting separate fault-injection tests to avoid mixing their results.

**Stale-command test**

```bash
python experiments/test_stale_motion.py
```

**Duplicate and reordered command test**

```bash
python experiments/test_motion_sequence.py
```

**Watchdog test**

With B3 running separately, send motion commands for five seconds and stop the A1 sender:

```bash
timeout --signal=INT --kill-after=2s 5s \
  .venv/bin/python -u mock/operator/a1_commands.py
```

The B3 controller records watchdog events containing `last_motion_ns`, `stop_ns`, and `elapsed_ms`, which can be used to verify the 300 ms deadline.

#### Evidence and Reports

All Task 2.2 measurement files are organized under:

`results/task2/fast_commands_tcp_udp/`

**Normal workload evidence**

- [Motion reception and application CSV](../results/task2/fast_commands_tcp_udp/evidence/motion_rx.csv) — Individual motion-command timestamps, sequence numbers, and decisions.
- [B3 controller log](../results/task2/fast_commands_tcp_udp/evidence/b3_controller.log) — Controller activity and diagnostic counters, if captured during the run.
- [Concurrent workload logs](../results/task2/fast_commands_tcp_udp/evidence/three_camera_logs/) — Experiment logs for camera streaming, motion generation, state updates, and queries.

**Safety test evidence**

- [Stale-command result](../results/task2/fast_commands_tcp_udp/safety_tests/stale/stale_result.csv).
- [Duplicate and reordered results](../results/task2/fast_commands_tcp_udp/safety_tests/duplicate_reordered/sequence_results.csv).
- [Watchdog summary](../results/task2/fast_commands_tcp_udp/safety_tests/watchdog/watchdog_summary.json).

**Consolidated report**

- [Task 2.2 report](../results/task2/fast_commands_tcp_udp/report/report.md).

These files provide the raw measurements and recorded controller decisions supporting the results in this section.

### 2.3 Reliable Commands: E-stop Delivery and Exactly-Once Execution

**Objective**

Evaluate whether reliable control commands can be delivered and applied exactly once and in order, even when all three camera streams are active.

The primary safety requirement is that every E-stop takes effect within 200 ms. The system must also report zero lost, duplicated, or reordered reliable-command applications.

#### Test Setup

The experiment used the same WSL2 network namespace configuration and hybrid TCP/UDP bridge as Sections 2.1 and 2.2.

Reliable commands travel over TCP between the two C++ bridges. A1 publishes commands to its local Zenoh router, and B3 receives them through the robot-side router.

Two command types were tested:

- **E-stop:** Latches the emergency-stop state and stops simulated motion.
- **Reset:** Clears the emergency-stop latch while keeping the robot stopped.

Each reliable command contains a unique command ID, opcode, and creation timestamp. A1 waits for an acknowledgment and retransmits the same command if the acknowledgment does not arrive within the configured timeout.

B3 stores the last applied reliable-command ID and E-stop state in SQLite. It rejects older commands and recognizes repeated command IDs without applying them again.

#### Measurement Method

The normal workload ran for 75 seconds with simultaneous head-camera and wrist-camera streaming, motion commands, state updates, and query traffic.

A1 sent 22 reliable commands at approximately three-second intervals, alternating between E-stop and Reset.

Both A1 and B3 recorded command events in CSV files. Records were matched using their unique command IDs.

The E-stop effect latency was calculated as:

`effect_latency_ms = (effect_ns - created_ns) / 1,000,000`

The analysis verified that:

1. Every unique command sent by A1 had exactly one application event at B3.
2. Every command was confirmed at A1.
3. Application order matched transmission order.
4. Every E-stop effect latency was within 200 ms.
5. No duplicate applications occurred.

#### Results — Normal Workload

| Metric | Measured result |
|---|---:|
| Test duration | 75 seconds |
| Reliable commands sent | 22 |
| E-stop commands | 11 |
| Reset commands | 11 |
| Commands applied at B3 | 22 |
| Commands confirmed at A1 | 22 |
| Lost commands | **0** |
| Duplicate applications | **0** |
| Reordered applications | **0** |
| E-stops exceeding 200 ms | **0** |
| Maximum E-stop effect latency | **6.431 ms** |

All 22 commands were applied exactly once and in the correct order during the recorded workload.

All 11 E-stops met the 200 ms effect-latency requirement. The maximum measured effect latency was 6.431 ms.

**Evidence:**

- [A1 reliable-command events](../results/task2/reliable_commands_tcp_udp/evidence/a1_reliable_events.csv)
- [B3 reliable-command events](../results/task2/reliable_commands_tcp_udp/evidence/b3_reliable_events.csv)
- [Per-command effect latency](../results/task2/reliable_commands_tcp_udp/report/command_results.csv)
- [Normal-workload summary](../results/task2/reliable_commands_tcp_udp/report/summary.json)

#### Fault Injection — Lost Acknowledgment

A separate test simulated the loss of the first acknowledgment after B3 had applied an E-stop.

The first command was committed successfully, but B3 deliberately suppressed its acknowledgment. After a 300 ms timeout, A1 retransmitted the same command ID.

B3 recognized the retransmission as a duplicate and returned the original effect timestamp without executing the command again.

| Measurement | Result |
|---|---:|
| A1 transmission attempts | 2 |
| A1 acknowledgment timeouts | 1 |
| B3 command receptions | 2 |
| B3 applications | **1** |
| Duplicate detections | 1 |
| Suppressed acknowledgments | 1 |
| Final confirmations | 1 |
| Original effect timestamp preserved | Yes |
| Test result | **PASS** |

This demonstrates that a lost acknowledgment does not cause the E-stop to be applied twice in the tested retry scenario.

**Evidence:**

- [A1 retry events](../results/task2/reliable_commands_tcp_udp/fault_tests/dropped_ack/a1_events.csv)
- [B3 application and duplicate events](../results/task2/reliable_commands_tcp_udp/fault_tests/dropped_ack/b3_events.csv)
- [A1 test output](../results/task2/reliable_commands_tcp_udp/fault_tests/dropped_ack/a1_reliable.log)

#### Fault Injection — Duplicate and Older Commands

The final fault-injection test verified that a repeated command ID and an older Reset command could not cause an unintended state change.

The test reused an already applied E-stop command ID, `1792091088427354726`, followed by a Reset command with the lower ID `1792091088427354725`.

| Test | Expected behavior | Observed result |
|---|---|---|
| Duplicate E-stop | Recognize previously applied command | `DUPLICATE` |
| Older Reset | Reject outdated command | `OLD_COMMAND` |
| Additional duplicate E-stop applications | 0 | 0 |
| Older Reset applications | 0 | 0 |

B3 recognized the duplicate E-stop and rejected the older Reset without recording another application.

The duplicate acknowledgment returned the timestamp of the original E-stop execution. Because this timestamp predates the new duplicate-test transmission, its difference from the new creation timestamp must not be interpreted as command latency.

**Evidence:**

- [Duplicate E-stop output](../results/task2/reliable_commands_tcp_udp/fault_tests/duplicate_reordered/duplicate_estop.log)
- [Older Reset output](../results/task2/reliable_commands_tcp_udp/fault_tests/duplicate_reordered/old_reset.log)
- [B3 decision records](../results/task2/reliable_commands_tcp_udp/fault_tests/duplicate_reordered/b3_events.csv)
- [Fault-test summary](../results/task2/reliable_commands_tcp_udp/fault_tests/duplicate_reordered/summary.json)

#### Observations and Limitations

The reliable-command path maintained low E-stop effect latency during simultaneous camera streaming. All transmitted commands in the normal-workload test were applied once and acknowledged, with no observed ordering violations.

The fault-injection tests also confirmed that B3 correctly handles a missing acknowledgment, a duplicate command ID, and an older command ID.

The event timestamps use the same WSL2 monotonic clock. The reported B3 effect timestamp is captured before SQLite commit completion, so it is an approximation of the completed simulated state transition rather than a post-commit measurement. The test also does not measure physical actuator stopping time.

The results support exactly-once application and ordering for the recorded workload and tested failure scenarios, rather than a universal guarantee under every possible failure.

#### Acceptance Result

**PASS — Reliable commands and E-stop safety in the tested scenarios**

- All 22 reliable commands were applied and confirmed.
- All 11 E-stops had measured effect latencies below 200 ms.
- No lost, duplicated, or reordered applications were observed.
- Retransmission after a lost acknowledgment did not produce a second application.
- Duplicate and older command IDs were correctly rejected or recognized.

The raw logs and per-command report are stored in `results/task2/reliable_commands_tcp_udp/`.