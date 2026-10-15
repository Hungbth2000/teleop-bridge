# Remote Teleoperation Bridge

**Coding Challenge — Remote Teleoperation Engineer (Networking & Streaming)**

**Implementation:** C++ transport bridge, Zenoh, Python simulation nodes  
**Environment:** Linux / WSL2, Linux network namespaces, `tc netem`  
**Status:** Core bridge implemented; transport and network validation partially completed

## Overview

This project implements a communication bridge between an operator and a simulated mobile robot.

The scenario represents an operator in Stuttgart controlling a robot in a warehouse in the Netherlands. The warehouse network may experience variable latency, packet loss, reduced bandwidth, and temporary disconnections during Wi-Fi roaming.

The system uses two local Zenoh routers, connected by a C++ bridge. Operator and robot applications communicate only with their respective local router, allowing the bridge to handle the differences between local and remote deployment.

The main engineering challenge is that teleoperation traffic has conflicting requirements. Motion commands, video frames, and robot-state updates must arrive quickly, while safety-related commands and configuration queries require reliable delivery.

The implemented solution separates best-effort real-time traffic from reliable, ordered traffic and evaluates several transport protocols.

---

# Task 1 — System Architecture

A concise two-page architecture design is maintained in `docs/architecture.md`. The principal design decisions are summarized here.

## 1.1 System topology

**Operator site**

- A1 publishes 100 Hz motion commands and safety-related commands.
- A2 receives and validates camera frames.
- A3 receives 50 Hz robot-state updates and sends configuration queries.
- A local Zenoh router communicates with the operator-side C++ bridge.

**Communication link**

- The operator-side and robot-side bridges exchange messages over an emulated network.
- Best-effort messages use UDP.
- Reliable ordered messages use TCP, QUIC, or KCP, depending on the experiment.

**Robot site**

- A local Zenoh router connects to the robot-side bridge.
- B1 publishes head-camera frames at 1280 × 720, 30 fps.
- B2 publishes two wrist-camera streams at 640 × 360, 30 fps.
- B3 receives control commands, maintains safety state, publishes robot state, and answers configuration queries.

In the test environment, the operator and robot run on one Linux host but use separate network environments.

The real deployment design assumes that the robot initiates outbound connectivity, since warehouse IT does not allow inbound ports. A production relay or rendezvous mechanism is part of the proposed deployment architecture, not a capability established by the current local testbed.

## 1.2 Traffic classification

| Lane | Direction | Frequency | Delivery strategy |
|---|---|---|---|
| A1 motion | Operator → Robot | 100 Hz | UDP, newest valid command wins |
| A2 head camera | Robot → Operator | 30 fps | UDP, fragmented frames |
| A2 wrist cameras | Robot → Operator | 30 fps each | UDP, fragmented frames |
| A3 robot state | Robot → Operator | 50 Hz | UDP, freshness prioritized |
| A3 configuration | Request/reply | On demand | Reliable ordered transport |
| B3 safety commands | Operator → Robot | On demand | Reliable ordered transport |

The bridge distinguishes messages that prioritize freshness from messages that require reliable ordered delivery.

For motion, a delayed old command may be less useful than a newer command. For safety and configuration, missing commands or replies require explicit handling.

## 1.3 Transport architecture

Three hybrid configurations have been implemented:

| Mode | Best-effort channel | Reliable channel |
|---|---|---|
| `hybrid` | UDP | TCP |
| `hybrid_quic` | UDP | QUIC |
| `hybrid_kcp` | UDP | KCP |

Standalone transport modes are also available for comparative testing.

The hybrid design avoids forcing high-frequency video and motion traffic through a single ordered reliable queue.

Reliable commands and queries use the selected reliable transport. The controller additionally maintains command identifiers and persistent state to support duplicate detection and recovery.

Transport reliability alone is not sufficient to guarantee exactly-once application effects, especially across disconnects and process restarts. That behavior must be verified at the application level.

## 1.4 Bandwidth plan

The assignment defines a robot-to-operator budget of 8 Mbit/s, temporarily reduced to 2 Mbit/s for 15 seconds every minute.

The intended priority is:

1. Safety-related control and essential signaling.
2. Robot-state information needed by the operator.
3. Head-camera video.
4. Wrist-camera video quality and frame rate.

Under restricted bandwidth, wrist-camera quality should be reduced before head-camera usefulness is sacrificed.

The final architecture document must specify the numerical bitrate allocated to each stream, account for transport overhead, and show how the bridge enforces the total budget.

**Verification pending:** The available experiment results do not yet demonstrate compliance with the 8-to-2 Mbit/s schedule or the required 80% timely, intact head-frame delivery at 2 Mbit/s.

## 1.5 Latency and safety requirements

| Requirement | Target |
|---|---|
| Motion freshness | Reject commands older than 150 ms |
| Motion ordering | Never apply an older command after a newer one |
| Motion watchdog | Stop if no fresh command arrives for 300 ms |
| E-stop effect | Within 200 ms |
| Head frames at 2 Mbit/s | At least 80% intact and within 200 ms |
| Bridge restart recovery | Control and video return within 1 second |

These are acceptance requirements, not measured achievements.

The architecture document must additionally provide a calculated per-hop latency budget for camera-to-screen and hand-to-motion paths. Measurements from the current testbed should then be used to determine whether the budget is realistic.

## 1.6 Roaming and failover

The proposed deployment uses Wi-Fi as the primary connection, with an optional cellular backup.

The robot must react safely when communications are interrupted:

- After 300 ms without a fresh motion command, the local motion watchdog should stop the robot.
- Following a two-second interruption, the connection must be re-established and old motion commands must not be replayed as current commands.
- Following a 30-second interruption, the robot must remain in a safe state until connectivity and control authorization are restored.

The final architecture document will include explicit event timelines for both interruption durations, as requested by the assignment.

**Scope limitation:** The current warehouse testbed emulates link outages but does not implement or validate physical Wi-Fi roaming or cellular handover.

## 1.7 Security

The design must consider unauthorized commands, command replay, endpoint impersonation, eavesdropping, and compromised credentials.

A production deployment should authenticate both bridge endpoints, encrypt communication, reject replayed commands, and store private keys in protected storage.

QUIC provides facilities for TLS-protected communication. However, the current laboratory configuration disables client-side server-certificate verification and must not be presented as production secure.

The current KCP test implementation also requires an authenticated security layer for real-world deployment.

Key distribution, certificate rotation, and production credential storage remain architecture-level design items rather than verified testbed capabilities.

---

# Task 2 — Build and Measure

## 2.1 Implementation environment

The testbed consists of:

- Linux / WSL2
- Operator and robot network environments
- Two Zenoh routers
- C++ bridge processes
- Python operator and robot simulation nodes
- Linux `tc netem` for network emulation
- CSV logging and automated experiment scripts

The robot-side network namespace uses the address `10.200.1.2`, while the operator-side interface uses `10.200.1.1`.

The bridge provides connectivity between the local Zenoh environments without requiring the simulation nodes to know the remote network topology.

## 2.2 Motion commands

A1 generates motion commands at approximately 100 Hz.

Each command contains a sequence number, creation timestamp, sender session identifier, and motion payload.

B3 validates command freshness and sequence ordering. The maximum accepted command age is 150 ms.

A motion watchdog is configured to detect missing fresh control updates and transition the simulated controller into a stopped state.

The controller uses sender-session identifiers to avoid treating delayed commands from a retired control session as valid new commands.

### Motion latency instrumentation

The robot-side controller records:

- Sender session identifier
- Sequence number
- Command creation timestamp
- Reception timestamp
- Delivery latency
- Whether the command was stale at reception

Reception measurements are recorded independently of whether the command is applied.

This allows evaluation of communication latency while E-stop is active.

Three preliminary smoke-test sessions produced p95 command-delivery latencies of 2.281 ms, 4.094 ms, and 3.059 ms, with no stale commands among the received samples.

These results have not yet been associated with a verified final transport/profile matrix.

## 2.3 Video streaming

The simulation generates deterministic H.264 camera frames.

Each frame has identifying information, and transmitted frames may be divided into fragments.

The operator-side receiver reconstructs frames and records complete, expired, invalid, or corrupted frames.

Camera CSV measurements include frame identifiers, capture timestamps, reception timestamps, and measured latency.

The primary assignment metric is:

**Good-frame percentage = intact frames displayed within 200 ms / captured frames × 100%.**

Frame completion alone is insufficient to establish this requirement.

## 2.4 Robot state and configuration queries

B3 publishes robot-state messages at approximately 50 Hz.

A3 records missing messages, invalid messages, duplicate or out-of-order reception, and message age.

Configuration queries use Zenoh's request-reply mechanism, forwarded through the reliable transport channel.

Each query records its status, first reply time, completion time, and number of replies.

Successful operation requires exactly one reply or an explicit timeout.

## 2.5 Reliable safety commands

B3 implements emergency-stop and reset commands.

The controller maintains a persistent SQLite record of safety-related command state. Command identifiers support duplicate detection and prevent repeated application of commands already processed.

E-stop prevents motion execution until the controller is reset.

The available logs demonstrate the existence of these mechanisms but do not yet establish the required maximum 200 ms command-to-effect latency.

Repeated E-stop tests, duplicate/reordering tests, and interruption tests are therefore still required.

## 2.6 Bandwidth enforcement

The assignment requires the bridge to enforce an 8 Mbit/s robot-to-operator budget that drops to 2 Mbit/s for 15 seconds each minute.

Validation must include actual transmitted-byte accounting, not only the configured target rate.

The final evidence should include:

- Configured bandwidth budget over time
- Measured bridge send rate
- Head and wrist video good-frame percentages
- Frame latency over time
- Motion-command age over time

The required combined timeline plot has not yet been produced from the available measurements.

## 2.7 Restart recovery

A compliant system must restore fresh motion-command delivery and valid video within one second after either bridge process restarts.

This should be measured separately for operator-side and robot-side bridge failures.

The recovery interval should be measured from the specified restart event to the first verified fresh command and first valid recovered video frame.

This acceptance test remains pending.

---

# Task 3 — Network and Transport Evaluation

## 3.1 Network emulation

Three network profiles were configured and tested.

| Profile | Measured mean RTT | Observed ICMP loss |
|---|---:|---:|
| Office LAN | 0.049 ms | 0% |
| Inter-city | 20.531 ms | 0.24% |
| Warehouse Wi-Fi | Approximately 92.19 ms | Approximately 3.65% |

The inter-city configuration used approximately 10 ± 2 ms delay and 0.1% loss in each direction.

Consequently, the expected round-trip ICMP loss is approximately 0.2%, consistent with the 0.24% observed across 5,000 probes.

The warehouse configuration used variable delay, a Gilbert–Elliott burst-loss model, temporary latency spikes, and periodic nominal 500 ms blackouts every 30 seconds.

The warehouse measurements were consistent with approximately 40 ms minimum, 90 ms average, and 280 ms maximum RTT.

Overall warehouse packet loss includes deliberate blackout intervals; it should not be interpreted as the ordinary baseline loss rate.

## 3.2 Office LAN transport comparison

The initial office LAN hybrid benchmarks used 75-second workloads.

| Metric | TCP/UDP | QUIC/UDP | KCP/UDP |
|---|---:|---:|---:|
| Head frames received | 2250 | 2250 | 2250 |
| Left wrist frames received | 2191 | 2211 | 2214 |
| Right wrist frames received | 2190 | 2212 | 2211 |
| Robot-state updates received | 3850 | 3850 | 3850 |
| Missing robot-state updates | 0 | 0 | 0 |
| State-age p95 | 4.158 ms | 2.686 ms | 4.242 ms |
| Successful configuration queries | 75/75 | 75/75 | 75/75 |

All three configurations successfully completed the office LAN workload.

These results establish an initial functional baseline, but they are not sufficient to determine the best transport across all required metrics.

In particular, the comparison must also include timely intact frames, A1 delivery latency, configuration-query response-time distributions, and B3 safety-command behavior.

## 3.3 Per-lane evaluation metrics

The final comparison will use:

| Traffic lane | Primary metrics |
|---|---|
| A1 motion | Reception-age p50/p95/p99, loss, stale rejection, safety violations |
| A2 head | Intact frames within 200 ms, frame-latency p50/p95/p99 |
| A2 wrist left | Intact frames within 200 ms, frame-latency p50/p95/p99 |
| A2 wrist right | Intact frames within 200 ms, frame-latency p50/p95/p99 |
| A3 state | Message-age p50/p95/p99, missing and out-of-order updates |
| A3 queries | Response-time p50/p95/p99, success, timeout, duplicate replies |
| B3 reliable commands | Effect latency, ACK latency, duplicate and ordering violations |
| Bridge recovery | Time until fresh commands and intact video return |

Measurements from separate benchmark sessions must not be combined without matching their session or run identifiers.

## 3.4 Design evolution and lessons learned

### Initial single-transport approach

The initial implementation supported using a single transport for different message types.

This simplified the communication architecture but exposed problems when reliable ordered transmission carried high-frequency, time-sensitive traffic.

An early all-KCP experiment under impaired network conditions showed significant queueing and degraded application performance.

The experiment was preliminary and used a different network configuration from the final corrected inter-city profile, so it should not be compared directly with later measurements.

### Adoption of hybrid routing

The bridge was extended to distinguish best-effort and reliable ordered delivery.

Motion, video, and state updates were assigned to UDP, while queries and reliable control commands were assigned to TCP, QUIC, or KCP.

This avoids making current real-time data wait unnecessarily behind the retransmission of older data in a shared reliable ordered stream.

It also permits the reliable transport to be evaluated separately from the real-time data path.

### Improvements to experimental reproducibility

During implementation, the test runner was modified to improve receiver cleanup and avoid overlapping experiment processes.

The inter-city network profile was corrected after checking measured RTT rather than relying only on configured delay.

Additional robot-side motion logging was introduced so that command-delivery latency could be evaluated independently of whether the safety controller accepted a command.

These changes illustrate an iterative process of identifying weaknesses in the implementation or evaluation method and improving them based on observable evidence.

## 3.5 Preliminary transport recommendation

The current evidence supports the use of a hybrid architecture for this simulated workload.

UDP is suitable for traffic where freshness matters more than guaranteed recovery of old data, provided the application rejects stale data and handles missing messages safely.

A reliable ordered channel remains necessary for control operations that require confirmed processing and for request-response communication.

The available office LAN measurements do not yet establish a definitive choice between TCP, QUIC, and KCP for the reliable channel.

A final choice requires comparing reliable-command latency, query response time, reconnection performance, and behavior during network interruption.

Security and deployment complexity must also be considered. For example, a transport with acceptable laboratory latency may still require additional authentication or operational infrastructure before production use.

---

# Conclusion

This project demonstrates a simulated multi-transport teleoperation communication system built with a C++ bridge and Zenoh-based applications.

The key design decision is to separate time-sensitive best-effort traffic from reliable ordered control traffic.

The implementation supports TCP/UDP, QUIC/UDP, and KCP/UDP hybrid configurations, deterministic camera workloads, motion-command validation, robot-state reporting, configuration queries, and persistent safety-related command state.

Network measurements validate the intended delay characteristics of the three emulated environments, and preliminary office LAN experiments demonstrate functional communication across all three hybrid configurations.

The remaining acceptance tests are particularly important: enforcing the bandwidth budget, meeting the 2 Mbit/s head-camera threshold, verifying E-stop effects within 200 ms, and recovering control and video within one second after bridge restarts.

The final evaluation should state explicitly which requirements were demonstrated, which were not met, and which remain unverified.

---

# Build, Run, and Reproduce

The final repository README will include the exact verified dependency installation, CMake build commands, Zenoh router startup, namespace setup, bridge launch commands, workload execution, and analysis steps.

Experiment outputs are retained in `results/`, including frame-level CSVs, motion-reception CSVs, query measurements, controller logs, and network-validation evidence.

The repository should provide a reproducible path from a clean environment to the reported results.
