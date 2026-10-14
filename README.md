# Remote Teleoperation Bridge

A local prototype of a bandwidth-aware bridge between isolated [Eclipse zenoh](https://zenoh.io/) networks for remote robot teleoperation. It prioritizes emergency control, forwards robot state and three camera streams, and records evidence about message delivery, latency, and bandwidth usage.

> **Implementation versus proposal:** The working prototype uses **two local zenoh routers and a C++ TCP bridge pair**. The original assignment design considered QUIC DATAGRAM/STREAM transport, an internet relay, TLS, Wi-Fi roaming, and cellular failover. Those are **proposed production extensions, not implemented or validated features** of this repository.

## 1. Scenario and requirements

The assignment scenario places the operator in **Stuttgart** and a warehouse robot in **the Netherlands**. Each site has a local zenoh network, and the warehouse is assumed not to accept inbound port forwarding. The prototype runs both sites locally under Ubuntu/WSL2; it does not connect to an actual robot or a real intercity WAN.

| Traffic | Nominal requirement | Intended behavior |
|---|---|---|
| Fast motion commands | 100 Hz | Latest valid command wins; stale/out-of-order commands must not actuate the robot |
| Reliable commands (E-stop, reset/enable/mode) | Event-driven | Ordered application, acknowledgments, and command-ID deduplication |
| Robot state | 50 Hz | Prefer fresh updates over queued old state |
| Head video | 1280 × 720, 30 fps | Reconstruct complete H.264 frames; discard expired/incomplete frames |
| Left and right wrist video | 640 × 360, 30 fps each | Lower priority than critical control |
| Queries | On demand | Matched reply or explicit timeout (design requirement; not fully validated here) |

Additional **design requirements** include rejecting fast commands older than 150 ms, stopping locally after 300 ms without fresh commands, emergency-stop effect within 200 ms when a link can deliver the command, and recovery within one second after a bridge restart when connectivity is available. **Do not interpret these as proven safety or recovery guarantees**: the final experiments below cover specific control and video behaviors, not every requirement in this table.

The robot-to-operator **outbound** application-byte budget is **8 Mbit/s normally**, reduced to **2 Mbit/s for 15 seconds of each minute**. This is not a bidirectional network cap.

## 2. Implemented architecture

```text
OPERATOR (simulated)                         ROBOT (simulated)
zenoh applications                           zenoh applications
         |                                            |
  local zenoh router                          local zenoh router
    TCP :7447                                   TCP :7448
         |                                            |
   C++ bridge process  <--- TCP :9000 --->   C++ bridge process
         |                                            |
   control sender /                         control executor /
   video receivers                         H.264 video senders
```

The two zenoh domains are isolated. Each C++ bridge connects to its local zenoh router, and the pair exchanges selected traffic over a TCP connection on localhost. This deliberately simplifies development and repeatable measurements; it **does not provide QUIC datagram semantics**, relay traversal, network encryption, or physical link failover.

The current priority scheduler uses:

| Priority | Traffic | Purpose |
|---|---|---|
| P0 | Critical control | Emergency-stop and reliable control-related traffic |
| P1 | Motion | Low-latency operator commands |
| P2 | Robot state | Telemetry and current state |
| P3 | Video | Largest and most disposable traffic; bounded video queue (capacity 64) |

The robot bridge has a shared outbound token-bucket limiter (configured budget 8/2 Mbit/s, 4,096-byte burst allowance) and publishes a local bandwidth-status topic at `teleop/bridge/bandwidth`. This budget is applied to serialized **application data** at the bridge; **TCP/IP and link-layer overhead are not included**. It is not equivalent to a measured over-the-air bandwidth cap.

### Reliable control

The prototype exercises E-stop and reset commands with unique IDs, a robot-side executor, persisted SQLite command deduplication, execution acknowledgements (`APPLIED`), and CSV event records. Retransmission/retry behavior can be observed in experiments; the final integrated trials did not require retries. Persistent command-ID suppression helps prevent duplicate effects after repeat delivery, but this local test is **not a certified exactly-once distributed safety system**.

### Three-camera video

- **Head:** 1280 × 720 H.264, 30 fps; prerecorded normal/degraded target representations of approximately 2 Mbit/s and 1.2 Mbit/s.
- **Left wrist:** 640 × 360 H.264, 30 fps; representations encoded with 400/250 kbit/s targets.
- **Right wrist:** 640 × 360 H.264, 30 fps; representations encoded with 400/250 kbit/s targets. Its static test footage compresses well below the requested target rates.
- The sender switches representations at GOP/IDR boundaries (GOP length 30), so switches can begin at independently decodable access units.
- Encoded H.264 access units are fragmented with a `VFR1` application header, transmitted on camera-specific zenoh topics, and reassembled with a **200 ms frame deadline**.
- The offline recorder sorts successfully reassembled access units by frame ID before writing Annex B `.h264` files. Missing frames are skipped rather than blocking later frames. This recorder is intended for **offline test inspection**, not bounded-memory deployment.

Source files are under `bridge/`, `mock/`, and `experiments/`.

## 3. Build and run

### Prerequisites

- Ubuntu 24.04 / WSL2 was used for development and validation.
- CMake, Ninja or another supported CMake generator, C++ compiler, Python virtual environment, FFmpeg/ffprobe, zenoh-compatible runtime, and the Python/C++ dependencies required by the repository.
- The C++ project has been built successfully using `cmake --build build` in the test environment. Consult `CMakeLists.txt` and the imports in the Python entry points for dependencies; this repository has not yet been verified as a one-command installation on a clean machine.

```bash
# From the project root, after installing dependencies and configuring CMake:
cmake --build build

# Inspect command-line options before starting video scripts:
python mock/video/head_receiver.py --help
python mock/video/wrist_receiver.py --help
python experiments/run_three_cameras.py --help
python experiments/run_integrated_test.py --help
```

**Start both local zenoh routers, the operator/robot C++ bridge processes, and the robot control executor before launching an integrated experiment.** Their exact invocation/configuration depends on the locally installed zenoh runtime and bridge executable; verify these in the source and local setup rather than assuming an internet-facing deployment.

### Three-camera recording experiment

With the routers and bridges running:

```bash
python experiments/run_three_cameras.py --duration 75
```

The runner starts three camera receivers, then three adaptive senders, and writes process logs under `results/three_camera_logs/`. Receivers can save the reconstructed files to `results/final_validation/` if recording options are configured in the runner.

Inspect the recorder output:

```bash
grep 'H264 REC' results/three_camera_logs/*_rx.log

for file in results/final_validation/*received.h264; do
    echo "=== $file ==="
    ffprobe -v error -count_frames -select_streams v:0 \
        -show_entries stream=codec_name,width,height,nb_read_frames \
        -of default=noprint_wrappers=1 "$file"
    ffmpeg -hide_banner -v error -xerror -i "$file" -f null -
    echo "Decoder exit status: $?"
done
```

### Integrated control and video experiment

With the robot-side reliable-command executor running, the combined experiment driver can be invoked as:

```bash
python experiments/run_integrated_test.py
```

Its control phase labels correspond to the configured budget seen when the test batch starts; they should **not** be interpreted as an exact per-command verification of the bandwidth phase.

### Analysis and archiving

```bash
python experiments/analyze_video_frames.py --help
python experiments/analyze_wrist_frames.py --help
python experiments/analyze_robot_bandwidth.py --help
python experiments/snapshot_integrated_results.py --help
```

Check each script's supported arguments before use. The snapshot script was used to archive an **earlier integrated run** to `results/final_validation/integrated_01/`; the later lossless H.264 recording is a **different run** and should not be conflated with that archived integrated test.

## 4. Experimental evidence

All measurements below are from **local simulation on WSL2**, using prerecorded video and an application-level bandwidth schedule. They are not measurements over a real Stuttgart–Netherlands connection, on real wireless links, or on robot actuators.

### 4.1 Three cameras with concurrent control

In the archived integrated experiment, all three adaptive camera streams were active while two E-stops and two resets were exercised in each labeled budget phase:

| Camera | On-time complete frames | Delivery fraction | Observed p95 delivery latency |
|---|---:|---:|---:|
| Head | 2,243 / 2,250 | 99.69% | 23.188 ms |
| Left wrist | 2,246 / 2,250 | 99.82% | 8.261 ms |
| Right wrist | 2,245 / 2,250 | 99.78% | 19.680 ms |
| **Combined** | **6,734 / 6,750** | **99.76%** | — |

Observed maximum per-camera completed-frame latency in that test was below 200 ms. This validates the application-level delivery deadline for **that local run**; it does not establish WAN or display latency.

### 4.2 Complete H.264 recording and decoding (separate run)

A subsequent 75-second three-camera experiment reconstructed **2,250 / 2,250 H.264 access units per camera** (6,750 total) with zero recorder-reported missing or duplicate frames. FFprobe counted 2,250 decoded frames from each saved file. FFmpeg completed error-check decoding with exit status `0` for all three:

| Camera | Resolution | Recorded/decoded frames | FFmpeg exit |
|---|---|---:|---:|
| Head | 1280 × 720 | 2,250 / 2,250 | 0 |
| Left wrist | 640 × 360 | 2,250 / 2,250 | 0 |
| Right wrist | 640 × 360 | 2,250 / 2,250 | 0 |

The successful recording does **not** imply that every other experiment was lossless.

### 4.3 Robot-outbound bandwidth

The candidate 75-second recording window was identified in robot bridge telemetry for session `robot_1791926452604633611` around elapsed 7,052–7,127 seconds. Summing cumulative transmitted application bytes across logged robot-outbound traffic kinds gives the following **five-second average** results for intervals whose endpoints had the same configured budget:

| Metric | Normal phase | Degraded phase |
|---|---:|---:|
| Configured budget | 8 Mbit/s | 2 Mbit/s |
| Stable intervals checked | 11 | 2 |
| Mean observed aggregate throughput | 2.518 Mbit/s | 1.604 Mbit/s |
| Peak observed aggregate throughput | 2.685 Mbit/s | 1.624 Mbit/s |
| Intervals above the reported budget | 0 | 0 |

Three additional five-second intervals were marked as **budget transitions** and excluded from the stable-budget comparison. One reported 2.263 Mbit/s against a **newly reported** 2 Mbit/s endpoint budget, but mixed-phase averaging prevents interpreting it as a definite violation. Sampling does not prove instantaneous conformance, and the token bucket allows a configured burst. In this recording run, nearly all measured outbound application bytes were video data.

### 4.4 E-stop and reset during integrated streaming

The archived integrated run contains **eight** control records: two E-stops and two resets per labeled phase. All eight had `CONFIRMED` outcomes, `APPLIED` acknowledgements, nonempty effect and confirmation latencies, and one send attempt (zero retries).

| E-stop measure | Normal label (2 trials) | Degraded label (2 trials) |
|---|---:|---:|
| Mean observed command-to-effect latency | 4.238 ms | 2.333 ms |
| Maximum observed command-to-effect latency | 5.249 ms | 2.606 ms |
| Maximum observed confirmation latency | 44.901 ms | 24.218 ms |

These are **observed software effects in a local test harness**, not measurements of mechanical emergency-stop performance. Four E-stop trials are too few to characterize tail reliability, and phase labeling is performed at batch start.

## 5. Safety, deployment and design assumptions

The system design distinguishes **remote command delivery** from **local robot safety**. During a full network blackout, no remote transport can guarantee that a newly sent E-stop reaches the robot within 200 ms. A real deployment needs independent local stopping behavior and appropriate safety validation.

Original scenario assumptions and proposed policies:

- Warehouse ingress is restricted; an outbound-initiated relay or VPN would be needed for production reachability.
- Fast commands should reject non-increasing sequence numbers and age above 150 ms; a robot-side watchdog should stop motion after 300 ms without fresh commands. These policies require end-to-end robot integration and explicit tests.
- Robot state is nominally 50 Hz and operator motion 100 Hz. The demonstrated experiments focus on the three camera feeds and reliable control.
- Wi-Fi roaming and an independently available cellular backup are **design candidates**, not part of the local prototype.
- The original bridge-restart target is recovery within one second when network connectivity exists; no conclusive restart test is included in the reported evidence.

### Proposed production evolution (not implemented)

The initial architecture favored QUIC DATAGRAM for video, motion and state and QUIC STREAM for reliable commands/queries, using an outbound-connected public relay to avoid warehouse inbound port forwarding. QUIC/TLS would protect individual connections to the relay, but **hop-by-hop TLS alone would not prevent a compromised relay from viewing payloads**; sensitive end-to-end payloads may require separate application-layer encryption. Authentication, authorization, key custody, session renewal and replay resistance must be engineered and tested.

A possible deployment would retain local zenoh at each site, use a relay (or a managed VPN), provide bounded queues and fresh-data policies, monitor link health, and handle Wi-Fi/cellular path changes. Proposed design times (e.g. ~150 ms link suspicion, five-second stable Wi-Fi failback) and the original per-hop camera/motion budgets (~175 ms camera-to-screen, ~100 ms hand-to-motion) are **planning allocations**, not measured performance. Likewise, equipment examples such as a European VPS and an LTE/5G router were only preliminary cost candidates, not purchased or validated components.

The initial proposal would suspend wrist feeds at 2 Mbit/s and lower head video to ~1.2 Mbit/s. **The actual prototype differs:** it keeps all three cameras active and switches their prerecorded high/low representations at GOP boundaries. The right-wrist static scene consumes less traffic than its nominal encoder target, so the observed degraded throughput should not be generalized to real high-motion footage.

## 6. Limitations and next steps

- **Transport:** Local TCP bridge, not QUIC DATAGRAM/STREAM; TCP head-of-line blocking and real WAN behavior have not been characterized.
- **Security:** No demonstrated production-grade cross-site TLS, mutual authentication, relay authorization or end-to-end encryption.
- **Network:** No measured real Wi-Fi interference, roaming, cellular failover, NAT traversal, relay outage or intercity RTT; the 8/2 Mbit/s schedule is an application-level limiter, not a simulated full network stack.
- **Video:** Prerecorded H.264 test sources, not camera capture or live hardware encoding; fixed 30 fps and representation switching at GOP boundaries. The offline recorder buffers full test sequences in memory.
- **Control:** Local software execution ACKs do not establish real actuator safety. Broader tests are still needed for stale motion inputs, watchdog behavior, query timeouts, concurrent failure/restart conditions and clock synchronization.
- **Statistics:** Limited trials, sampled throughput, and no claims of worst-case latency or guaranteed frame delivery.
- **Testing tooling:** The last recorded C++ build succeeded, but the Python test runner was unavailable (`No module named pytest`) and CTest reported no registered tests. Test-suite passing status remains **unverified** until dependencies are installed and tests are executed.

## 7. Repository layout

```text
bridge/           C++ message transport, scheduling and bandwidth limiting
mock/             Simulated operator/robot components and H.264 senders/receivers
experiments/      Integrated runners, telemetry analysis and result snapshots
tests/            Python and C++ test sources
scripts/          Supporting scripts
results/          Generated telemetry, control logs and recordings (Git-ignored)
README.md         Architecture, setup, evidence and constraints (this document)
```

Generated `.h264`, `.csv`, `.sqlite3` and process logs remain local and should not be committed accidentally. For portable results, export a deliberately selected small validation snapshot and give it an unambiguous run identifier.

## 8. Reference

- [Eclipse zenoh](https://zenoh.io/)
- [MsQuic](https://github.com/microsoft/msquic) — referenced for the **proposed**, not implemented, production QUIC path.
