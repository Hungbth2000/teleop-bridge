# Remote Teleoperation Bridge

A C++ networking bridge for a remote robot teleoperation system,
developed as part of the Remote Teleoperation Engineer coding challenge.

## Objectives

- Forward data between local zenoh routers at the operator and robot sites.
- Support freshness-sensitive control and robot-state traffic.
- Deliver reliable safety commands and request/reply messages.
- Prioritize traffic under bandwidth constraints.
- Measure latency, throughput, packet loss, and recovery behavior.
- Evaluate transport protocols under different network conditions.

## Project Structure

- `bridge/` - C++ bridge implementation
- `mock/` - Simulated operator, cameras, and robot controller
- `tests/` - Automated tests
- `experiments/` - Network experiments and analysis
- `docs/` - Architecture and design decisions

## System Architecture

The proposed architecture connects a remote operator in Stuttgart to a robot in a warehouse in the Netherlands. The design uses local zenoh routers for communication between application nodes and C++ bridges for communication over the public Internet.

A public QUIC relay is used because the warehouse network does not permit inbound connections. Both bridges initiate outbound QUIC connections to the relay.

### Architecture Overview

- **Operator site (Stuttgart):** Operator application nodes A1–A3, local zenoh router, and C++ bridge.
- **Robot site (Netherlands):** Robot application nodes B1–B3, local zenoh router, and C++ bridge.
- **Public relay:** Cloud-hosted server forwarding traffic between the two bridge connections.
- **Primary network:** Warehouse Wi-Fi.
- **Backup network:** LTE/5G cellular connectivity.

Local application communication uses zenoh over TCP. WAN communication uses QUIC with integrated TLS 1.3 over UDP/IP.

### Communication Protocols

| Data lane | Direction | Transport |
|---|---|---|
| Head camera | Robot → Operator | QUIC DATAGRAM |
| Wrist cameras | Robot → Operator | QUIC DATAGRAM |
| Fast movement commands (100 Hz) | Operator → Robot | QUIC DATAGRAM |
| Reliable commands | Operator → Robot | QUIC STREAM |
| Robot state (50 Hz) | Robot → Operator | QUIC DATAGRAM |
| Query / reply | Bidirectional request/response | QUIC STREAM |

Reliable commands require application-level IDs, deduplication, ordered execution, and acknowledgments. The bridge scheduler prioritizes critical traffic and limits outgoing bandwidth.

H.264 is the proposed video codec. Actual encoder bitrates and frame-delivery performance must be validated experimentally.

### Bill of Materials

| Component | Location | Estimated cost | Purpose |
|---|---|---|---|
| Existing operator workstation | Stuttgart | €0 incremental | Runs A1–A3, zenoh router and bridge |
| Existing robot computer | Netherlands | €0 incremental | Runs B1–B3, zenoh router and bridge |
| Eclipse zenoh | Both sites | Free | Local messaging and query/reply |
| Custom C++ bridge | Both sites | No license cost | WAN transport, scheduling and rate limiting |
| MsQuic | Bridges and relay | Free | QUIC streams, datagrams and TLS 1.3 |
| H.264 encoder/decoder | Robot/operator | €0 incremental if supported | Video compression and playback |
| Hetzner Cloud VPS | Germany | Approx. €5–15/month | Public relay |
| Existing warehouse Wi-Fi/gateway | Netherlands | €0 incremental | Primary connectivity |
| Teltonika RUTX50 5G router | Netherlands | Approx. €480–700 | Cellular backup option |
| Cellular SIM/data plan | Netherlands | Approx. €10–30/month | Backup Internet connectivity |

Prices are preliminary estimates, not supplier quotations. Cloud traffic, IPv4 charges, taxes, hardware integration, and development costs are excluded.

### Bandwidth Plan and Degradation Strategy

#### 1. Requirements and Assumptions

The robot communicates with a remote operator through a public QUIC relay. The robot's outbound WAN bandwidth is limited to **8 Mbit/s during normal operation** and **2 Mbit/s during degraded operation**, with degradation lasting 15 seconds per minute.

The system must deliver at least **80% of head-camera frames intact within 200 ms** during the 2 Mbit/s condition.

The bandwidth limit applies to **robot outbound traffic**, not the combined bidirectional traffic. Operator-to-robot commands are therefore budgeted separately.

The following estimates assume:

- H.264 video encoding, with configurable bitrate.
- QUIC DATAGRAM for video, fast commands, and robot state.
- QUIC STREAM for reliable commands and query/reply.
- IPv4 networking with an assumed 1,100-byte video payload per packet.
- Robot state messages of approximately 100 bytes at 50 Hz (assumed size).
- Wrist-camera traffic can be reduced or suspended during degradation.

Encoder bitrates and packet overhead are initial design assumptions, not measured values.

#### 2. Camera Bandwidth Calculation

**2.1 Uncompressed video**

The required raw video bitrate is calculated as:

\[
R_{\text{raw}} = W \times H \times FPS \times BPP
\]

Assuming uncompressed RGB video (24 bits per pixel):

| Camera | Resolution | FPS | Calculation | Raw bitrate |
|---|---|---:|---|---:|
| Head | 1280 × 720 | 30 | 1280 × 720 × 30 × 24 | 663.55 Mbit/s |
| Left wrist | 640 × 360 | 30 | 640 × 360 × 30 × 24 | 165.89 Mbit/s |
| Right wrist | 640 × 360 | 30 | 640 × 360 × 30 × 24 | 165.89 Mbit/s |
| **Total** | | | | **995.33 Mbit/s** |

The uncompressed bandwidth substantially exceeds the available WAN capacity. Video compression is therefore required.

**2.2 Estimated H.264 bitrate**

H.264 bitrate depends on scene complexity, movement, encoder configuration, and acceptable image quality. It cannot be determined exactly from resolution and frame rate alone.

For initial planning, the following encoder targets are selected:

| Camera | Normal target | Degraded target |
|---|---:|---:|
| Head (720p, 30 fps) | 3.0 Mbit/s | 1.2 Mbit/s |
| Left wrist (360p, 30 fps) | 1.0 Mbit/s | Disabled |
| Right wrist (360p, 30 fps) | 1.0 Mbit/s | Disabled |
| **Total video payload** | **5.0 Mbit/s** | **1.2 Mbit/s** |

The corresponding compression ratio relative to uncompressed RGB is:

\[
C = \frac{R_{\text{raw}}}{R_{\text{encoded}}}
\]

For the head camera:

- Normal: 663.55 / 3.0 ≈ **221:1**
- Degraded: 663.55 / 1.2 ≈ **553:1**

For each wrist camera during normal operation:

- 165.89 / 1.0 ≈ **166:1**

These ratios describe the compression required to reach the selected targets. They do not demonstrate that the resulting video quality is sufficient.

At 1.2 Mbit/s and 30 fps, the head camera has an average encoded frame size of:

\[
S_{\text{frame}} = \frac{1{,}200{,}000}{30 \times 8}
= 5{,}000\text{ bytes}
\]

Actual H.264 frame sizes vary, especially between independently coded frames and predicted frames.

#### 3. Network Protocol Overhead

The compressed video is fragmented into application messages and transmitted using QUIC DATAGRAM over UDP/IP.

For estimation, assume the following packet structure:

| Component | Assumed size |
|---|---:|
| H.264 payload chunk | 1,100 bytes |
| Application fragmentation header | 12 bytes |
| QUIC DATAGRAM frame header | 3 bytes |
| QUIC packet header | 4 bytes |
| QUIC authentication tag | 16 bytes |
| UDP header | 8 bytes |
| IPv4 header | 20 bytes |
| **Total IP packet size** | **1,163 bytes** |

The estimated overhead is:

\[
O = \frac{1163-1100}{1100} \times 100
\approx 5.73\%
\]

Therefore, the estimated IP-layer bitrate for a video stream is:

\[
R_{\text{WAN}} = R_{\text{video}} \times \frac{1163}{1100}
\]

For the degraded head camera:

\[
R_{\text{head,WAN}} = 1.2 \times \frac{1163}{1100}
\approx \boxed{1.269\text{ Mbit/s}}
\]

This estimate excludes additional QUIC ACK/control traffic, retransmissions, variable packetization, and link-layer overhead. The assumed packet sizes are not fixed values defined by QUIC.

#### 4. Robot-to-Operator Bandwidth Allocation

Robot outbound traffic includes camera video, robot state, query replies, application acknowledgments, and QUIC control traffic.

Robot state is estimated at 100 bytes per update, transmitted at 50 Hz:

\[
R_{\text{state,payload}} = 100 \times 50 \times 8
= 40\text{ kbit/s}
\]

Assuming one packet per update with 63 bytes of combined overhead:

\[
R_{\text{state,WAN}} = (100+63)\times50\times8
= 65.2\text{ kbit/s}
\]

**4.1 Normal operation: 8 Mbit/s**

| Data stream | Payload bitrate | Estimated IP-layer bitrate |
|---|---:|---:|
| Head camera | 3,000 kbit/s | 3,172 kbit/s |
| Left wrist camera | 1,000 kbit/s | 1,057 kbit/s |
| Right wrist camera | 1,000 kbit/s | 1,057 kbit/s |
| Robot state | 40 kbit/s | 65 kbit/s |
| **Estimated total** | **5,040 kbit/s** | **5,351 kbit/s** |
| **Unallocated capacity** | | **2,649 kbit/s** |

The remaining capacity accommodates transport overhead not included in the model, acknowledgments, query replies, encoder bursts, and other traffic.

**4.2 Degraded operation: 2 Mbit/s**

| Data stream | Payload bitrate | Estimated IP-layer bitrate |
|---|---:|---:|
| Head camera | 1,200 kbit/s | 1,269 kbit/s |
| Left wrist camera | 0 | 0 |
| Right wrist camera | 0 | 0 |
| Robot state | 40 kbit/s | 65 kbit/s |
| **Estimated total** | **1,240 kbit/s** | **1,334 kbit/s** |
| **Unallocated capacity** | | **666 kbit/s** |

The estimated degraded traffic uses approximately:

\[
\frac{1.334}{2.0}\times100 \approx 66.7\%
\]

of the available robot outbound bandwidth.

The remaining approximately 666 kbit/s is a planning reserve, not guaranteed available capacity. The actual transmitted rate must be measured and constrained by the bridge's bandwidth limiter.

#### 5. Operator-to-Robot Bandwidth

Operator-to-robot traffic is budgeted separately because the specified 2 Mbit/s cap applies to robot outbound traffic.

Fast movement commands contain approximately 100 bytes and are transmitted at 100 Hz:

\[
R_{\text{fast,payload}} = 100 \times 100 \times 8
= \boxed{80\text{ kbit/s}}
\]

Assuming 63 bytes of overhead per command:

\[
R_{\text{fast,WAN}} = (100+63)\times100\times8
= \boxed{130.4\text{ kbit/s}}
\]

| Data stream | Estimated bitrate | Transport |
|---|---:|---|
| Fast movement commands | 80 kbit/s payload; ~130 kbit/s IP-layer | QUIC DATAGRAM |
| E-stop, enable, mode changes | Event-driven, size TBD | QUIC STREAM |
| Query requests | Event-driven, size TBD | QUIC STREAM |
| QUIC acknowledgments | Variable | QUIC control |

Although operator-to-robot traffic is not subject to the robot outbound cap, it can still affect latency through Wi-Fi contention, congestion, and packet loss.

#### 6. Degradation Strategy at 2 Mbit/s

When the available robot outbound bandwidth decreases, the bridge applies the following policy.

**Priority 1 — Preserve safety and essential state**

Robot state updates, reliable-command acknowledgments, and essential protocol control traffic remain prioritized. The robot controller independently enforces command age, sequence ordering, and the 300 ms movement-command watchdog.

**Priority 2 — Preserve head-camera delivery**

The head camera receives the primary video allocation. Its H.264 encoder target is reduced from 3.0 Mbit/s to an initial 1.2 Mbit/s.

The objective is to preserve timely head-camera frames rather than maximize visual quality. The 1.2 Mbit/s target must be validated against the requirement that at least 80% of head frames arrive intact within 200 ms.

**Priority 3 — Reduce wrist-camera traffic first**

Wrist-camera encoder bitrate and frame rate are reduced before head-camera traffic. Under the proposed conservative 2 Mbit/s profile, both wrist streams are suspended.

**Priority 4 — Discard expired video**

The bridge uses bounded queues and frame deadlines. Stale frames and incomplete frames that cannot meet their deadline are discarded instead of being retained in growing transmission queues.

If network conditions remain insufficient, the system must favor safe robot behavior over continued teleoperation.

#### 7. Bandwidth Enforcement and Validation

The robot bridge uses a priority-aware scheduler and rate limiter to control WAN transmission.

The scheduler selects traffic according to priority, while the limiter enforces the configured 8 Mbit/s or 2 Mbit/s budget.

The implementation must account for the bytes included in the assignment's actual-byte measurement, including relevant QUIC/UDP/IP headers, control packets, and retransmissions. Limiting only application payload bytes is insufficient.

Tasks 2 and 3 will validate:

- Actual robot outbound send rate against the configured cap.
- Head-camera frame integrity and arrival latency.
- Percentage of head frames arriving intact within 200 ms.
- Command age, safety violations, and reliable-command latency.
- Behavior during bandwidth degradation, packet loss, and temporary outages.

**Conclusion:** The proposed design allocates approximately 1.33 Mbit/s of estimated IP-layer traffic to head video and robot state during degraded operation, leaving approximately 0.67 Mbit/s unallocated. Wrist-camera transmission is sacrificed first, while head-camera delivery and essential state traffic remain prioritized. All bitrate targets are provisional and must be verified experimentally.

### Latency Budget

Two end-to-end latency paths are considered: camera-to-screen (robot to operator) and hand-to-motion (operator to robot).

For camera-to-screen communication, the proposed budget is 175 ms, consisting of 33 ms for camera acquisition, 15 ms for H.264 encoding, 2 ms for local zenoh delivery, 5 ms for bridge scheduling, 65 ms for robot-to-relay transmission, 3 ms for relay forwarding, 20 ms for relay-to-operator transmission, 2 ms for local delivery, 10 ms for decoding, and 20 ms for display.

For hand-to-motion communication, the proposed normal-network budget is 100 ms, consisting of 10 ms for input sampling, 2 ms for local zenoh delivery, 3 ms for bridge scheduling, 20 ms for operator-to-relay transmission, 3 ms for relay forwarding, 45 ms for relay-to-robot transmission, 2 ms for local delivery, 5 ms for controller processing, and 10 ms for actuator response.

These values are design targets rather than measured latencies. The warehouse Wi-Fi RTT may vary between 40 and 280 ms, potentially causing deadline violations. To minimize latency, the bridges use priority-aware scheduling and bounded queues, while outdated video frames and movement commands are discarded.

The robot controller independently rejects commands older than 150 ms and stops after 300 ms without fresh commands. Tasks 2 and 3 will measure actual command age, video delivery latency, and deadline compliance under simulated network conditions.

### Roaming, Cellular Failover, and Outage Recovery

The robot uses warehouse Wi-Fi (`wlan0`) as its primary network connection and an independently connected LTE/5G modem (`wwan0`) as backup. Overlapping Wi-Fi coverage and 802.11k/v/r support are preferred to reduce roaming interruption. Both paths reach a public QUIC relay using outbound UDP/443, avoiding inbound firewall requirements at the warehouse.

The robot bridge monitors link events, QUIC path health, and application-level responses. As an initial configuration, path probes run every 50 ms, with a path considered suspect after approximately 150 ms without a response. The bridge attempts QUIC path migration to cellular, falling back to a new outbound connection if migration fails. These thresholds and recovery times require experimental validation.

**2-second outage:** At 0–150 ms, the bridge detects a possible connection failure and begins failover. If no fresh movement command reaches B3 for 300 ms, its independent watchdog stops the robot. If cellular connectivity is restored, the bridge resumes communication, discards stale queued data, and synchronizes session state. Motion resumes only after valid fresh commands and any required re-enable checks. When Wi-Fi returns, the bridge waits for stable connectivity before switching back.

**30-second outage:** If neither Wi-Fi nor cellular can reach the relay, B3 stops after 300 ms without fresh commands and remains stopped throughout the outage. The bridges retry connectivity while the operator interface indicates disconnection. Once the network returns, the bridges reconnect, discard outdated commands and frames, synchronize sequence numbers and robot state, and require fresh control authorization before resuming motion.

B3 rejects commands older than 150 ms and never applies an older sequence number. Network recovery cannot bypass these checks. Wi-Fi roaming and cellular failover improve availability but cannot guarantee uninterrupted operation or meet the 200 ms e-stop deadline during a complete network blackout.

### Security: Threats, Defences and Key Storage

The teleoperation system is exposed to several threats, including network eavesdropping, unauthorized access, command injection, replay attacks, denial-of-service, and compromise of the public relay.

Both the operator and robot bridges establish outbound QUIC connections secured with TLS 1.3 to the relay. Mutual certificate authentication (mTLS) identifies authorized devices, while the relay enforces an allowlist and associates connections with the correct teleoperation session. Because the relay terminates QUIC, transport encryption alone does not provide end-to-end confidentiality; additional application-level encryption would be required to protect data from a compromised relay.

Motion commands include sequence numbers and timestamps. B3 rejects commands older than 150 ms or with sequence numbers older than the last applied command. Reliable commands use unique IDs, ordered processing, and deduplication to prevent repeated execution. Priority scheduling and bounded queues reduce congestion-related risks, while the independent 300 ms B3 watchdog stops motion when fresh commands are missing.

Each bridge has a separate device identity and private key, preferably stored in a TPM-backed or OS-protected key store. The relay stores its TLS private key in restricted server-side storage. Public CA certificates and device allowlists are distributed to the relevant endpoints. Private keys are never included in the source repository. Credentials can be rotated or revoked if a device is compromised.

Local zenoh access is restricted to authorized processes. After reconnection, the robot verifies session authorization and command sequence state before accepting new motion commands.

### Architectural Trade-offs (weighted decisions)

**1. QUIC vs. TCP/UDP:** QUIC was selected because it supports unreliable DATAGRAM delivery for video, fast motion commands, and robot state, alongside reliable STREAM delivery for critical commands and queries. TCP-only transport was rejected due to head-of-line blocking, while plain UDP would require custom security, reliability, and congestion-control mechanisms. QUIC still requires application-level prioritization and deduplication.

**2. Public relay vs. direct connection/VPN:** Both bridges establish outbound QUIC connections to a public relay, avoiding inbound firewall changes at the warehouse. Direct peer-to-peer connectivity was rejected because NAT traversal and firewall permissions cannot be assumed. A site-to-site VPN was not selected because it introduces additional network configuration and IT dependencies. The relay introduces an extra hop and availability risk.

**3. Adaptive streaming vs. fixed/equal allocation:** Priority-aware bandwidth management was selected to protect head-camera delivery under the 2 Mbit/s robot outbound limit. Normal video targets are 3.0 Mbit/s for the head and 1.0 Mbit/s per wrist camera. During degradation, wrist streams are suspended first and the head target is reduced to 1.2 Mbit/s. Fixed or equal-rate allocation was rejected because it risks congestion or sacrifices bandwidth needed for the head-camera deadline. Encoder targets and delivery performance will be validated in Tasks 2 and 3.
