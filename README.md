# Remote Teleoperation Bridge

**Task 1 · Proposed architecture (pre-measurement)** — C++ bridges connect unchanged local [zenoh](https://zenoh.io/) applications between an operator in Stuttgart and a warehouse robot in the Netherlands. **Design targets and estimates are not test results.** Task 2/3 measurements will determine which assumptions hold.

## 1. End-to-end topology

![System Architecture](https://github.com/Hungbth2000/teleop-bridge/blob/main/docs/images/architecture.png)

**Lane mapping:** QUIC **DATAGRAM** = head/wrist H.264 fragments, newest-wins motion commands (100 Hz), newest-wins robot state (50 Hz). QUIC **STREAM** = ordered reliable e-stop/enable/mode commands and zenoh query/reply. Application envelopes carry `session_id`, sequence/command ID, timestamps, frame/fragment IDs and deadlines. Video reassembly drops incomplete/expired frames. Reliable commands require **B3 execution ACK, ordered processing and deduplication**; QUIC delivery alone is not exactly-once execution. Queries receive one matched reply or an explicit deadline timeout. QUIC DATAGRAM support must be negotiated. Camera encoding at B1/B2 is a proposed implementation assumption; if these nodes publish raw frames, encode at the robot bridge instead without changing the WAN lanes.

The **warehouse permits outbound UDP/443** (assumption to confirm); no inbound warehouse port is required. Each bridge independently initiates a connection to the relay. The relay forwards two bidirectional connections, so QUIC/TLS is **hop-by-hop**, not end-to-end through the relay.

## 2. Bill of materials

| Product / software | Location | Incremental cost (rough) | Why |
|---|---|---:|---|
| Existing operator PC + robot computer, cameras | Both sites | €0 assumed | Reuse assignment hardware; CPU/H.264 acceleration to verify |
| [Eclipse zenoh](https://zenoh.io/) + custom C++ bridge | Both sites | €0 license | Local pub/sub/query API; isolated WAN policy |
| [MsQuic](https://github.com/microsoft/msquic) | Both bridges + relay | €0 license | TLS 1.3 QUIC streams, DATAGRAM, migration capabilities |
| H.264 encoder/decoder (hardware if supported) | Robot / operator | €0 assumed | Low-latency compressed video; no B-frames |
| [Hetzner Cloud](https://www.hetzner.com/cloud) EU VPS | Relay | ~€5–15/month | Public reachable endpoint; bandwidth/egress fees extra |
| Existing Wi-Fi AP/gateway | Warehouse | €0 assumed | Primary uplink, roaming coverage |
| [Teltonika RUTX50](https://teltonika-networks.com/products/routers/rutx50) (candidate) + SIM | Robot / cellular network | ~€480–700 + €10–30/month | Independent 5G/LTE backup; power, mounting and coverage to verify |

*Costs are unverified planning estimates, not quotations; taxes, data egress, installation and integration excluded.*

## 3. Bandwidth and graceful degradation

**Scope:** 8 Mb/s normal and 2 Mb/s for 15 s/minute are **robot-outbound** caps, not bidirectional totals. Operator→robot traffic has its own budget. Decimal Mb/s used throughout.

**Source/calculation:** RGB24 uncompressed `width × height × 30 fps × 24 bits` = **663.55 Mb/s** (head 1280×720) and **165.89 Mb/s each** (640×360 wrists). H.264 targets below are **selected rate-control settings, not derived codec guarantees**. Example IP overhead: 1,100 B encoded video + 12 B fragment + 3 B DATAGRAM frame + 4 B QUIC header + 16 B authentication tag + 8 B UDP + 20 B IPv4 = **1,163 B**. Estimated video wire multiplier = `1163/1100 = 1.0573`; actual headers, small final fragments, QUIC control, link-layer airtime and bursts vary.

| Robot → operator | Normal H.264/payload | Normal IP estimate | Degraded payload | Degraded IP estimate |
|---|---:|---:|---:|---:|
| Head 720p30 | 3.00 Mb/s | 3.172 Mb/s | 1.20 Mb/s | 1.269 Mb/s |
| Left wrist 360p30 | 1.00 | 1.057 | **off** | 0 |
| Right wrist 360p30 | 1.00 | 1.057 | **off** | 0 |
| State 50 Hz × assumed 100 B | 0.040 | 0.065 | 0.040 | 0.065 |
| **Estimated total** | **5.040** | **5.351** | **1.240** | **1.334** |
| **Remaining under cap** | — | **2.649** | — | **0.666** |

State estimate: `100×50×8 = 40 kb/s` payload; assuming one 100+63 B packet/update: `163×50×8 = 65.2 kb/s` IP. **Operator→robot** fast commands: `100 B×100 Hz×8 = 80 kb/s` payload, ~`(100+63)×100×8 = 130.4 kb/s` IP; reliable commands and queries are event-driven, not included in this fixed rate. Robot-side QUIC ACKs, execution ACKs and query replies **do** consume robot egress.

**Sacrifice order at 2 Mb/s:** (1) reserve capacity and scheduler priority for critical command responses, state and QUIC control; (2) suspend both wrist videos; (3) lower head encoder from 3.0 to **1.2 Mb/s**; (4) drop expired video fragments/frames rather than queue them. The head target averages `1.2e6/(30×8) = 5,000 B/frame`, but I-frames can burst. Use bounded queues, priority-aware packet scheduling, encoder feedback and an **actual-byte egress limiter** (including transport overhead); merely limiting H.264 bytes is insufficient. **≥80% of head frames intact within 200 ms at 2 Mb/s is a test criterion, not a prediction.**

## 4. Per-hop latency budgets (ms)

These are **engineering allocations** for a nominal usable path, **not measured one-way delays** or guarantees under Wi-Fi impairment. End-to-end camera presentation includes display time; the assignment's 200 ms head-frame criterion is **frame arrival**, not screen presentation.

| Camera → screen stage | ms | Hand → motion stage | ms |
|---|---:|---|---:|
| Camera acquisition (up to 1 frame at 30 fps) | 33 | Input sampling / command creation (100 Hz cycle) | 10 |
| H.264 encode | 15 | Local zenoh | 2 |
| Robot local zenoh | 2 | Operator bridge queue | 3 |
| Robot bridge queue/fragment | 5 | Operator → relay WAN | 20 |
| Robot Wi-Fi + WAN → relay | 65 | Relay forward | 3 |
| Relay forwarding | 3 | Relay → robot WAN + Wi-Fi | 45 |
| Relay → operator WAN | 20 | Robot bridge + zenoh | 2 |
| Operator bridge + zenoh | 2 | B3 validation/control cycle | 5 |
| H.264 decode | 10 | Actuator initial response | 10 |
| Screen/render | 20 | — | — |
| **Total screen latency** | **175** | **Total motion latency** | **100** |

**Camera frame arrival budget:** 175−10−20 = **145 ms** before decode/display, nominally leaving 55 ms relative to the 200 ms delivery threshold. **Hand-to-B3 application:** 100−10 = **90 ms** nominally; B3 rejects age **>150 ms**, never applies older sequence numbers, and stops after **300 ms** without fresh commands. Warehouse Wi-Fi RTT in the proposed impairment test ranges **40–280 ms**; RTT/2 is only a rough one-way proxy if paths are symmetric. High delay or blackout can violate either budget. Measure one-way age using synchronized clocks or a clearly documented common time base.

## 5. Roaming, outages and recovery

**Primary:** overlapping warehouse AP coverage, preferably 802.11k/v/r where supported; `wlan0` preferred. **Backup:** independently registered, already-online LTE/5G on `wwan0`. Robot bridge monitors link events and application/QUIC path health, attempts QUIC path migration over cellular, and falls back to a fresh outbound QUIC connection. Proposed probes **50 ms**, path *suspect* after ~**150 ms** silence; jitter can cause false positives, so path switching uses hysteresis (e.g. **5 s** stable Wi-Fi before failback). These timers are **design settings to test**, not hardware guarantees.

| Time after loss | 2 s Wi-Fi outage (cellular may work) | 30 s outage (both paths unavailable) |
|---|---|---|
| 0–150 ms | Bridge detects link/probe loss; operator notices stale state/video; try cellular | Same; reconnect attempts begin |
| By 300 ms without fresh commands | **B3 stops motion locally**, independent of transport | **B3 stops motion locally** |
| 0.3–2 s | If cellular succeeds, migrate/reconnect, discard stale queues, refresh state/video; otherwise stay stopped | Stay stopped; retry with bounded backoff; operator UI shows disconnected |
| At 2 s / 30 s | Wi-Fi returns: probe, avoid flapping; only resume with fresh authorized commands | Network returns: re-authenticate, reconcile session/command IDs and state, discard old commands/video |
| After recovery | Resume only after B3 safety checks / re-enable if latched | Require explicit re-enable after prolonged stop (proposed policy) |

**Restart requirement:** target **≤1 s** for bridge restart recovery of control/video **when network paths are available**; this must be measured in Task 2. Neither failover nor a reliable stream can guarantee remote e-stop within 200 ms during a complete blackout; B3's local watchdog is the fallback.

## 6. Security and key custody

| Threat | Defence | Keys / trust location |
|---|---|---|
| Wi-Fi/Internet sniffing, MITM | QUIC TLS 1.3, verify relay certificate; mTLS client identities | Robot/operator private identity keys: TPM/OS-protected storage (prototype: service-owned `0600` files); trusted CA public certs on endpoints |
| Unauthorized operator, command injection/replay | Relay device allowlist + per-session authorization; B3 sequence, timestamp, ID/dedup and watchdog checks; zenoh local ACLs | Relay allowlist / trust anchors; B3 authorization state and last applied ID |
| Compromised relay | Relay can see/change data under hop-by-hop QUIC; optional **end-to-end AEAD** for command/video payloads, with endpoint-only keys | E2E private/session keys **only** on operator/robot, never relay |
| Flooding, stale commands, stolen credentials | Priority scheduling, bounded queues, rate limits; revoke/rotate credentials, fail safe | Relay TLS private key: restricted VPS secret store; **no private keys in Git** |

## 7. Three architectural trade-offs

| Decision | Chosen | Rejected / reason | Cost of choice |
|---|---|---|---|
| **Transport** | QUIC DATAGRAM + STREAM | TCP-only: stale data blocked by retransmission; raw UDP: build security/reliability ourselves | QUIC scheduling, DATAGRAM negotiation, app-level exactly-once logic |
| **Reachability** | Public outbound QUIC relay | Direct P2P: NAT/firewall traversal uncertain; site VPN: warehouse IT dependency | Extra hop, relay cost and trust/failure domain |
| **Degradation** | Prioritize head + state; drop wrists first | Fixed/equal video rates: overload 2 Mb/s or starve required head frames | Encoder adaptation and precise byte accounting |

## 8. Task 2/3 evidence and revision log

| Check | Target / question | Measured | Design change |
|---|---|---|---|
| 2 Mb/s egress | Count actual transmitted bytes under cap | **Pending** | Pending |
| Head frames | ≥80% intact and ≤200 ms at 2 Mb/s | **Pending** | Pending |
| Fast control | Age p50/p95/p99; zero stale/out-of-order applications | **Pending** | Pending |
| Reliable / query | Exactly-once ordered execution; one reply or timeout | **Pending** | Pending |
| E-stop | ≤200 ms when link can deliver; test under video saturation | **Pending** | Pending |
| Bridge restart | Control/video recover within 1 s on available link | **Pending** | Pending |
| Network impairment | LAN, intercity, jitter/loss/blackouts, failover behavior | **Pending** | Pending |

**Number provenance:** camera sizes/rates, command/state frequencies, age/watchdog thresholds, link caps and deadline come from the **challenge specification**; raw bitrates, payload rates, packet-overhead examples and table totals are **calculations shown above**; encoder targets, packet sizes, latency allocations, detection timers, prices and cellular equipment are **explicit assumptions** to validate with datasheets, quotations and Tasks 2/3. Do not treat proposed latency or frame success rates as achieved measurements.

---

**Repository layout:** `bridge/` C++ implementation · `mock/` simulated endpoints · `tests/` assertions · `experiments/` impairment runs/plots · `docs/` supporting notes.
