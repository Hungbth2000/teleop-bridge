# Teleoperation Operator

**A Zenoh-based teleoperation prototype with C++ network bridges, hybrid TCP/UDP transport, and repeatable network-impairment tests.**

An operator in Stuttgart controls a simulated wheeled, dual-arm robot in a Netherlands warehouse. The target deployment must tolerate packet loss, constrained bandwidth, Wi-Fi roaming and temporary outages while operating behind warehouse NAT without inbound ports.

> **Status:** Local Zenoh applications, C++ bridges, simulated video/control, and Linux network-emulation experiments have been exercised. The public VPS relay, physical cameras/actuators, warehouse AP roaming, cellular failover, and production security are **proposed—not deployed or validated**. All reported short application latencies use a common clock on one WSL2 host, not geographically separated devices.

## Contents

- [System at a glance](#system-at-a-glance)
- [Build and run locally](#build-and-run-locally)
- [Task 1 — Architecture and design decisions](#task-1--architecture-and-design-decisions)
- [Task 2 — Build and measure](#task-2--build-and-measure)
- [Task 3 — Network impairment testing](#task-3--network-impairment-testing)
- [Evidence and reproducibility](#evidence-and-reproducibility)
- [Limitations and next steps](#limitations-and-next-steps)

## System at a glance

![architecture](https://github.com/Hungbth2000/teleop-bridge/blob/main/docs/images/architecture2.png)

| Channel | Direction | Local test transport | Purpose |
|---|---|---|---|
| Head + two wrist cameras | Robot → operator | UDP | Prefer current frames; avoid retransmission-induced queues |
| Motion commands | Operator → robot | UDP | 100 Hz updates; reject stale/out-of-order commands |
| Robot state | Robot → operator | UDP | 50 Hz updates |
| E-stop / Reset | Operator → robot | TCP | Ordered/retried commands, deduplicated at controller |
| Configuration query/reply | Both | TCP | Reliable Zenoh requests and responses |

The Zenoh routers connect **local applications** and the corresponding bridges. In the testbed they listen at `127.0.0.1:7447` (operator) and `127.0.0.1:7448` (robot). Internet-facing authentication/tunneling is a design requirement, **not a proven property of the tested bridge**.

## Build and run locally

This section describes the **single-host Linux/WSL2 testbed**, not the proposed VPS/Wi-Fi/LTE deployment. It uses an operator in the default namespace and a robot in `teleop-robot`. Start each long-running service in its own terminal. Commands below use the supplied repository startup examples. Other mock-node entry points and dependency versions still need verification against the source tree.

### 1. Dependencies

**Platform:** Ubuntu/Linux (WSL2 is the tested environment), `sudo`, Python 3 with virtual-environment support, a C++20-capable compiler and CMake 3.20 or newer, Zenoh router (`zenohd`), and Linux networking utilities (`iproute2`, `tc`/`netem`, `ping`). The camera decoder in Task 2 uses PyAV. Exact compiler, Zenoh, Python and library versions are **not documented in the supplied material** and should be pinned once confirmed from the repository.

Install commonly required system tools on Ubuntu:

```bash
sudo apt update
sudo apt install -y build-essential cmake pkg-config git \
  python3 python3-venv python3-pip iproute2 iputils-ping
```

`tc` comes from `iproute2`. **Install `zenohd` using the version documented by your repository** and verify it is on `PATH` (`zenohd --help`). The C++ bridge additionally depends on native `zenohc`, `zenohcxx`, and MsQuic (`libmsquic.so.2`); the KCP source is included in `third_party/kcp/`. Install compatible native releases before building. These are **not** installed by `requirements.txt`.

Prepare Python from the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
# If provided by the repository:
python -m pip install -r requirements.txt
```

The `requirements.txt` file covers Python dependencies only; it does not install the native C/C++ libraries needed by the bridge.

### Build the C++ bridge

From the repository root, configure and build the executable with CMake:

```bash
cd ~/projects/teleop-bridge

# Confirm compiler and build tool versions
cmake --version
g++ --version

# Configure the CMake project (requires installed native dependencies)
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release

# Compile the C/C++ sources, including vendored KCP where configured
cmake --build build --parallel "$(nproc)"

# Verify that the operator/robot bridge executable was created
test -x build/teleop_bridge && echo "Bridge build successful"
```

The project requires **CMake ≥ 3.20** and **C++20**. Native dependencies are **Zenoh C (`zenohc`)**, **Zenoh C++ (`zenohcxx`)**, and **MsQuic (`libmsquic.so.2`)**; KCP's C source is vendored under `third_party/kcp/`. Build the *CMake target*, rather than compiling a single `.c` or `.cpp` file with `gcc`/`g++`, because the bridge links multiple sources and libraries. Install the native dependencies separately before running CMake.

After changing C/C++ source code, rebuild with:

```bash
cmake --build build --parallel "$(nproc)"
```

If you need a clean build, delete only the generated build directory and reconfigure:

```bash
rm -rf build
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel "$(nproc)"
```

If configuration fails with *package not found* or linking fails with *library not found*, check that the native Zenoh and MsQuic development libraries are installed and discoverable by CMake. These commands build the bridge binary; the next sections start the network namespace, Zenoh routers, bridges, and mock nodes.

### 2. Set up the network namespace

```bash
sudo bash scripts/setup_network.sh
ip -br addr show veth-teleop-op
sudo ip netns exec teleop-robot ip -br addr show veth-teleop-rb
ping -c 3 10.200.1.2
sudo ip netns exec teleop-robot ping -c 3 10.200.1.1
```

| Endpoint | Namespace | Interface | IPv4 |
|---|---|---|---|
| Operator | Default | `veth-teleop-op` | `10.200.1.1/24` |
| Robot | `teleop-robot` | `veth-teleop-rb` | `10.200.1.2/24` |

The setup script creates or verifies the veth pair and tests connectivity. The robot namespace shares the same Linux kernel, so monotonic timestamps are comparable in these experiments.

### 3. Start the Zenoh routers

Start each router in a separate terminal from the repository root, after configuring the namespace:

**Terminal 1 — operator router (default namespace):**

```bash
zenohd --listen tcp/127.0.0.1:7447
```

**Terminal 2 — robot router (`teleop-robot` namespace):**

```bash
sudo ip netns exec teleop-robot \
  zenohd --listen tcp/127.0.0.1:7448
```

These loopback endpoints are local **within their respective namespaces**. They are used by the local applications and bridges, not as the cross-namespace connection.

### 4. Start the C++ bridges

With both routers running, open two more terminals in the repository root. Start the operator bridge first, then the robot bridge.

**Terminal 3 — operator bridge (default namespace):**

```bash
TELEOP_TRANSPORT=hybrid \
TELEOP_TCP_BIND=10.200.1.1 \
TELEOP_UDP_LOCAL=10.200.1.1 \
TELEOP_UDP_PEER=10.200.1.2 \
./build/teleop_bridge operator
```

**Terminal 4 — robot bridge (`teleop-robot` namespace):**

```bash
sudo ip netns exec teleop-robot env \
  TELEOP_TRANSPORT=hybrid \
  TELEOP_TCP_HOST=10.200.1.1 \
  TELEOP_UDP_LOCAL=10.200.1.2 \
  TELEOP_UDP_PEER=10.200.1.1 \
  ./build/teleop_bridge robot
```

| Bridge | Namespace | TCP role | Local IP | UDP peer |
|---|---|---|---|---|
| Operator | Default | Listens on `10.200.1.1` | `10.200.1.1` | `10.200.1.2` |
| Robot | `teleop-robot` | Connects to `10.200.1.1` | `10.200.1.2` | `10.200.1.1` |

Both bridges use `TELEOP_TRANSPORT=hybrid` (UDP real-time lane; TCP reliable lane). These commands connect over the **local veth pair**, not through the proposed public VPS relay.

### 5. Start the mock nodes

Run B3 before sending motion commands from A1. Make sure the `results/` directory exists before using `tee`.

**Terminal 5 — B3 robot controller (`teleop-robot` namespace):**

```bash
mkdir -p results
sudo ip netns exec teleop-robot \
  .venv/bin/python -u mock/robot/b3_controller.py \
  2>&1 | tee results/task2_recovery_b3.log
```

The pipeline writes B3's combined standard output/error to the terminal and `results/task2_recovery_b3.log`. The file name comes from the provided recovery-test command; use a different log name for other experiments if you need to preserve separate logs. The `.venv` environment is addressed by its explicit executable path, so activating it in the shell is not required for this command.

**Terminal 6 — A1 motion sender (operator namespace):**

```bash
.venv/bin/python -u mock/operator/a1_commands.py
```

| Mock node | Namespace | Function | Startup status |
|---|---|---|---|
| A1 commands | Operator | 100 Hz motion commands | Command shown above |
| A2 viewer | Operator | Receive/decode camera streams | Direct command not yet confirmed |
| A3 state/queries | Operator | Receive state and issue queries | Direct command not yet confirmed |
| B1 head camera | Robot | H.264 1280×720 at 30 fps | Direct command not yet confirmed |
| B2 wrist cameras | Robot | Two H.264 640×360 at 30 fps | Direct commands not yet confirmed |
| B3 robot controller | Robot | Validate/apply motion, E-stop, watchdog, state | Command shown above |

The integrated runner in the next section handles the multi-camera experiment; avoid independently starting duplicate mock publishers if the runner already launches them. Consult `experiments/run_three_cameras.py` before running it alongside manually started nodes.

### 6. Run the integrated workload and analyze results

With the two routers, both bridges, and required mock services running, the documented integrated runner exercises the three-camera workload (including concurrent control/state/query traffic as configured by the runner):

```bash
sudo -E .venv/bin/python experiments/run_three_cameras.py \
  --duration 75 \
  --robot-netns teleop-robot
```

For Task 2's good-frame analysis, archive raw output before another run and then execute:

```bash
python experiments/analyze_phase_good_frames.py \
  --evidence results/task2/good_frames_tcp_udp/good_frame_evidence \
  --report results/task2/good_frames_tcp_udp/good_frame_report
```

To reproduce Task 3's packaged video metrics:

```bash
python experiments/analyze_task3_video.py
```

Task 3 network impairments are configured using `experiments/intercity_network.py` and `experiments/warehouse_network.py`. **Their invocation/stop flags are not available here**: check each script's help/source before launching, and remove any remaining `tc` rules when returning to the Office LAN baseline. Other fault-injection entry points and evidence locations appear in Tasks 2–3 below.

### 7. Stop and clean up

Stop mock senders/receivers, bridges and Zenoh routers (usually `Ctrl+C` in their terminals), then stop any Task 3 impairment process. Verify `tc qdisc show dev veth-teleop-op` and the robot-side interface to make sure a network profile has not leaked into the next test. Leave the namespace in place for subsequent runs; `scripts/setup_network.sh` is designed to verify/reuse an existing consistent configuration.

> **Before treating this as a fully copy-paste build guide:** confirm the Zenoh version/flags, Python dependency manifest, C++ bridge build targets and startup options, and B1/B2/B3/A2/A3 entry points against the actual repository. These details cannot be reliably reconstructed from experiment reports alone.

## Task 1 — Architecture and design decisions

### Proposed deployment and bandwidth

The deployment design has both bridges initiate outbound connections to a public VPS, avoiding inbound warehouse firewall openings. Warehouse Wi-Fi is the primary path; LTE is a separate backup uplink. Neither the relay nor failover was exercised in Tasks 2–3.

The **nominal encoded-stream estimates** below are design inputs from the architecture diagram, **not measured camera encoder rates**. The robot uplink is the capacity-constrained direction.

| Traffic | Planned nominal rate | At 2 Mbit/s capacity |
|---|---:|---|
| Head H.264, 1280×720, 30 fps | ~1.20 Mbit/s | Keep first; reduce quality if necessary |
| Two wrist H.264 streams | ~0.25 Mbit/s each | Lower quality / disable first |
| Robot state | ~0.04 Mbit/s | Preserve |
| **Nominal media + state** | **~1.74 Mbit/s** | Must leave room for transport overhead and bursts |
| Motion (opposite direction) | **~0.08 Mbit/s payload** | 100 bytes × 100 Hz × 8 |

The bridge test configures a robot-outbound **8 → 2 Mbit/s** budget for part of its run. Task 2 verifies application-level head-frame timeliness under that *configured* budget, **not** strict aggregate wire-byte compliance with 2 Mbit/s. The diagram's local `~174/~186 Mbit/s` TCP annotations are not validated WAN bitrate requirements.

### Target latency and safety policy

| Budget component | Camera → decoded frame | Hand → simulated motion |
|---|---:|---:|
| Capture/input | 30 ms | 5 ms |
| Local route/bridge | 10 ms | 5 ms |
| WAN including relay | 45 ms | 45 ms |
| Decode/validation/actuation | 35 ms | 15 ms |
| Jitter allowance | 60 ms | — |
| **Calculated design target** | **180 ms** | **70 ms** |

These values are **engineering allocations**, not measured per-hop physical latencies. In particular, 45 ms one-way WAN time is not guaranteed under the warehouse profile. The local controller rejects motion older than **150 ms**, rejects duplicate/older sequences and obsolete sessions, and triggers a simulated stop no later than **300 ms** after fresh accepted motion ceases (implemented watchdog threshold: **280 ms**). The remote E-stop target is **200 ms**, but cannot be guaranteed during a network blackout; a real robot requires independent onboard safety provisions.

### Proposed roaming and outage behavior

Plan overlapping 5 GHz AP coverage with 802.11k/v where supported; validate 802.11r client compatibility before enabling it. Keep cellular as a warm backup, and clear queued stale controls after any reconnection. Transport migration is not automatically seamless merely because a second interface exists.

| Time / event | Intended response |
|---|---|
| Command becomes >150 ms old | B3 rejects it on arrival |
| ≤300 ms without fresh commands | Local watchdog stops simulated motion |
| 2-second disruption | Attempt Wi-Fi recovery or cellular switchover; reauthenticate and require fresh data before enabling control |
| 30-second disruption | Stay stopped; use bounded retries; refresh state and require explicit re-enable before motion |

These are **policies**, not measured 2-second/30-second failover timelines. Task 3 tested approximately 0.5-second emulated blackouts, without real LTE or physical actuators.

### Security and estimated equipment

Production risks include control injection/replay, forged video/state, relay compromise, exposed credentials and traffic flooding. Proposed protections: mutual authentication via TLS 1.3/QUIC or an authenticated tunnel, per-topic authorization, session/sequence/freshness checks, rate limits, and locally enforced fail-safe behavior. Store robot secrets in protected OS storage/TPM when available, operator secrets in a platform keystore, and relay service credentials separately. **Do not deploy the lab QUIC mode without certificate verification or standalone unauthenticated KCP on the public Internet.**

| Component | Site | Rough budget / status |
|---|---|---|
| Linux computers + Zenoh/C++ bridges | Both | Existing in testbed; production SKUs TBD |
| 3 H.264 cameras | Robot | SKUs / price TBD; simulated streams tested |
| 2 × UniFi U6+ APs | Warehouse | ~€178 total; proposed |
| Teltonika RUT241 **LTE** router | Robot | ~€184; proposed (not 5G) |
| Hetzner relay VPS | Cloud | ~€5.99/month before applicable extras; proposed |

Prices are historical budgetary estimates, not verified current quotes. See [UniFi](https://eu.store.ui.com/eu/en/products/u6-plus), [RUT241](https://geizhals.de/teltonika-rut241-lte-wlan-router-rut241034000-a3820183.html), and [Hetzner](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/). Installation, SIM, mounting, power, camera hardware and labor are not included.

**Decisions weighed:** (1) Reject one ordered reliable queue for all data in favor of UDP for freshness-sensitive streams and TCP for reliable control; preliminary all-KCP tests exhibited queue buildup. (2) Prefer outbound relay to prohibited robot-side inbound ports, though it has not been implemented. (3) Prioritize head video and control over wrist quality when bandwidth falls; strict egress shaping and automatic adaptation still need verification.

## Task 2 — Build and measure

The 75-second integrated tests used three prerecorded H.264 streams (head **1280×720**, two wrists **640×360**, all 30 fps), 100 Hz motion updates, state, reliable commands and configuration queries. Stream-frame timestamps share a WSL2 monotonic clock. **Task 2 video timing ends at successful PyAV decode—not physical screen presentation.**

### 2.1 Video: good frames within 200 ms

Frames are uniquely identified, reassembled, checked for length/CRC32, decoded with PyAV, checked for expected dimensions, and counted as *good* only if decoded within 200 ms of capture. The outbound budget cycles through **45 s at 8 Mbit/s, 15 s at 2 Mbit/s** (per 60 s cycle).

| Stream | Configured budget | Good / captured | Good rate | Capture→decode p95 |
|---|---:|---:|---:|---:|
| Head | 8 Mbit/s | 1,453/1,453 | 100% | 13.364 ms |
| **Head** | **2 Mbit/s** | **797/797** | **100%** | **48.074 ms** |
| Left wrist | 8 Mbit/s | 1,451/1,451 | 100% | 6.489 ms |
| Left wrist | 2 Mbit/s | 774/799 | 96.87% | 71.458 ms |
| Right wrist | 8 Mbit/s | 1,451/1,451 | 100% | 6.330 ms |
| Right wrist | 2 Mbit/s | 773/799 | 96.75% | 64.240 ms |

**Result:** Meets the **≥80% on-time, intact head-frame** criterion under the *configured* 2 Mbit/s phase. Overall, head **2,250/2,250**, left **2,225/2,250**, and right **2,224/2,250** were good. This does **not** independently prove byte-accurate egress shaping or pixel-level equality.

### 2.2 Motion: freshness, ordering and watchdog

A1 emits 100-byte commands at 100 Hz. B3 computes command age from shared monotonic timestamps, applies only valid current-session increasing sequences, and rejects stale, duplicated or out-of-order messages. The cap in §2.1 applies to **robot→operator**, not the command direction.

| Measurement | Result |
|---|---:|
| Received / applied in normal workload | 7,561 / 7,561 |
| Applied-command age p50 / p95 / p99 | **1.997 / 4.300 / 4.779 ms** |
| Maximum applied-command age | 9.974 ms |
| Detected normal-run safety violations | 0 |
| Injected stale command (201.329 ms) | Rejected; not applied |
| Injected duplicate seq 100 / older seq 99 | Both rejected; not applied |
| Stop after A1 interruption | **282.170 ms**, simulated `moving=False` |

**Result:** Tested acceptance conditions pass. The 300 ms stop criterion applies to **simulated controller state**, not actual motor braking. The 7,561 records are **received at B3**; complete delivery of all commands sent by A1 was not established.

### 2.3 Reliable E-stop / Reset

A1 sends uniquely identified reliable commands via **TCP**. B3 uses SQLite to track applied IDs and latch state; retries retain the same ID, enabling deduplication.

| Measurement | Result |
|---|---:|
| E-stop / Reset commands | 11 / 11 |
| Applied and acknowledged | **22 / 22** |
| Lost / duplicate / reordered applications | **0 / 0 / 0** |
| Maximum E-stop effect latency | **6.431 ms** (all 11 ≤200 ms) |
| Injected lost ACK | 2 sends, 2 receptions, **1 application** |
| Repeated E-stop / older Reset ID | `DUPLICATE` / `OLD_COMMAND`; no extra effect |

**Result:** Exactly-once *application in the recorded scenarios*, not a universal guarantee. The effect timestamp is recorded **before SQLite commit completion**; neither durable post-commit latency nor physical E-stop effect was measured. A loss-of-connectivity interval longer than 200 ms precludes a guaranteed remote E-stop effect within 200 ms.

### 2.4 Configuration queries

| Scenario | Measured outcome |
|---|---|
| 75 s workload, 1 query/s | **75/75 successful**, 0 duplicate replies; first-reply mean 5.404 ms, p95 10.535 ms, p99 11.059 ms |
| 8 concurrent queries | **8/8 successful**, latency 2.83–5.26 ms |
| B3 delay 4,000 ms; A3 timeout 3,000 ms | **0/3 valid replies**; completion ~3,019–3,081 ms; client remained operational |

The timeout test demonstrates graceful zero-reply handling; the CSV alone does not distinguish a true timeout from another cause of no valid replies. Eight requests do not characterize maximum capacity.

### 2.5 Bridge-process recovery

Separate 40-second runs killed one bridge via `SIGKILL`, kept it offline for approximately **5 s**, then restarted it. Recovery times are measured **after process relaunch**, excluding the forced downtime.

| Path recovered after relaunch | Operator bridge restart | Robot bridge restart |
|---|---:|---:|
| Head video | 123.661 ms | 51.088 ms |
| Left wrist video | 124.156 ms | 44.407 ms |
| Right wrist video | 138.945 ms | 23.127 ms |
| Fresh motion | 117.282 ms | 20.440 ms |
| **Slowest measured path** | **138.945 ms** | **51.088 ms (calculated)** |

These results are local **process-restart recovery**, not restoration from bridge failure, physical roaming or Internet failover. The original Task 2 source was truncated during the robot-side table; the 51.088 ms maximum is calculated from the four surviving path values and should be checked against the complete report.

## Task 3 — Network impairment testing

Task 3 used Linux `tc netem` on the same WSL2 virtual link—not physical multi-site Internet or warehouse Wi-Fi.

### 3.1 Profiles and validated conditions

| Profile | Configured impairment | Observed RTT min / mean / max | Aggregate ICMP loss |
|---|---|---|---:|
| Office LAN | None | 0.020 / **0.049** / 0.340 ms | 0% |
| Inter-city | 10 ± 2 ms delay and 0.1% loss per direction | 16.937 / **20.416** / 24.552 ms | 0.24% |
| Warehouse | 45 ± 25 ms delay/direction, burst loss, spikes, ~500 ms blackout every 30 s | 41.0 / **91.362** / 273.0 ms* | 3.133% |

*Corrected warehouse RTT excludes four anomalous 0 ms samples; originals are retained.* The network probe recorded three blackouts of **509.841, 526.587 and 510.107 ms**. Background loss was *configured* at roughly 1% per direction, but its separate contribution was not isolated from blackout loss. These loss percentages are observed aggregate ICMP round-trip outcomes, not one-way background-loss estimates.

### 3.2 On-time received video and queries

Task 3 matches transmitter/receiver frame IDs and counts capture-to-**reception** latency of 0–200 ms. Unlike Task 2, these data **do not independently verify H.264 decoding**.

| Metric | Office | Inter-city | Warehouse |
|---|---:|---:|---:|
| Head good-frame delivery | 100.00% | 99.20% | **96.22%** |
| Left wrist delivery | 97.38% | 99.69% | 97.07% |
| Right wrist delivery | 97.33% | 99.78% | 97.29% |
| Head p95 latency | 23.211 ms | 52.061 ms | **82.016 ms** |
| Left wrist p95 latency | 13.711 ms | 38.601 ms | 72.498 ms |
| Right wrist p95 latency | 18.516 ms | 39.313 ms | 71.700 ms |
| Successful queries | 75/75 | 75/75 | 75/75 |

**Evidence caveat:** The office and inter-city values came from archived matching TX/RX records whose precise active network profile and bridge mode were **not independently logged**. The warehouse results were reproduced in a clean 75-second retest with separate impairment evidence. Comparisons are informative, not fully controlled comparisons of all three profiles.

### 3.3 Warehouse motion and blackout recovery

| Clean warehouse motion test | Measured |
|---|---:|
| Received commands (one sender session) | 7,365 |
| Applied | 4,380 |
| Rejected for older sequence ordering | **2,985 (40.5% of received)** |
| Missing sequences within observed span | 200 |
| Duplicate sequence records / stale applied | **0 / 0** |
| Applied-command age mean / p95 / p99 | **39.165 / 60.751 / 68.886 ms** |
| Maximum applied age | 139.232 ms |

Sequence checks prevented old updates being applied after newer ones, but the **40.5% rejection rate** suggests a motion-smoothness risk. It is not proof of physical jitter or a measured loss rate from all generated A1 commands.

| Application-trial blackout | #1 | #2 |
|---|---:|---:|
| Duration | 520.709 ms | 510.461 ms |
| Time **after blackout end** to first applied motion | 29.773 ms | 26.245 ms |
| Age of first recovered command | 26.741 ms | 24.510 ms |

Application traffic recovered quickly **once the blackout ended**. These intervals omit the blackout itself, and neither watchdog/E-stop during those blackouts nor actual actuator recovery was independently measured.

## Evidence and reproducibility

### Task 2

- Video inputs, receiver/decoder CSVs, bridge rates and logs: `results/task2/good_frames_tcp_udp/good_frame_evidence/`; generated summaries: `results/task2/good_frames_tcp_udp/good_frame_report/`.
- Motion receiver and fault tests: `results/task2/fast_commands_tcp_udp/` (including `evidence/motion_rx.csv`, stale/sequence tests and `safety_tests/watchdog/watchdog_summary.json`).
- E-stop/Reset and lost-ACK tests: `results/task2/reliable_commands_tcp_udp/`.
- Query, concurrency and timeout tests: `results/task2/request_reply_tcp_udp/`.
- Bridge restart: `results/task2/recovery_tcp_udp/operator_bridge_restart/` and corresponding robot-side recovery artifacts (check the complete source report).

Recompute video performance from archived Task 2 evidence:

```bash
python experiments/analyze_phase_good_frames.py \
  --evidence results/task2/good_frames_tcp_udp/good_frame_evidence \
  --report results/task2/good_frames_tcp_udp/good_frame_report
```

For targeted motion checks, see `experiments/test_stale_motion.py` and `experiments/test_motion_sequence.py`. The controller records watchdog `last_motion_ns`, `stop_ns` and `elapsed_ms` in its event evidence. Archive outputs from each run before starting a new one to avoid mixing records.

### Task 3

Raw network, blackout, controller and recovery evidence: `results/task3/real_network/`. Selected camera runs are packaged under `results/task3/real_network/selected_video_runs/`, with per-stream `tx.csv`/`rx.csv` and a `manifest.json` containing run IDs, source paths, frame counts and SHA-256 checksums.

```bash
python experiments/analyze_task3_video.py
```

This verifies the packaged evidence hashes, joins frame identifiers, and recomputes on-time reception. `experiments/package_task3_video.py` documents extraction from cumulative source logs; **repackaging** requires the original cumulative logs, but **reanalyzing** requires only the packaged evidence.

## Limitations and next steps

1. **Verify real network limits.** Account for complete outbound wire bytes, burst rates and competing flows; configured bridge budgets are not proof of a physical 2 Mbit/s cap.
2. **Improve warehouse motion continuity.** Investigate packet reordering, receive scheduling and gaps between accepted updates while preserving freshness/sequence protection.
3. **Test actual fail-safe behavior.** Instrument watchdog/E-stop during blackouts and measure physical braking, state persistence, reset/re-enable authority and relay disconnects.
4. **Integrate production networking/security.** Implement and test the VPS relay, TLS certificate validation/authentication, Wi-Fi roaming, cellular switchover and key provisioning/revocation.
5. **Validate physical end-to-end timing.** Repeat camera-to-display and operator-to-actuator measurements on distinct hosts with an explicit cross-host clock synchronization strategy; compare real H.264 output against the design bitrate assumptions.
6. **Complete experiment provenance.** Record exact `tc` rules, bridge mode, software revision, start/stop times, full TX/RX counts and source report files for each run.

**Overall:** The prototype demonstrated timely video, safe application-layer rejection of obsolete commands, reliable-command deduplication, functioning queries and fast *post-restoration* local recovery. It **has not yet demonstrated** the complete secure Stuttgart-to-Netherlands deployment or physical robot safety under outages.
