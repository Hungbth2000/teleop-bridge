# Task 1 — End-to-End Teleoperation Architecture

**Scenario.** An operator in Stuttgart controls a wheeled, dual-arm robot in a Dutch warehouse. Warehouse Wi-Fi can lose packets, slow down, or disappear during AP roaming; warehouse IT allows no inbound ports. **Status legend:** **[Built]** exercised in the single-host testbed; **[Proposed]** deployment design, not implemented or verified.

## 1. Topology, protocols, and link budgets

```text
STUTTGART / OPERATOR                                        NETHERLANDS / WAREHOUSE
A1 100 Hz motion, safety                                      B1 head 720p30 (H.264)
A2 head + 2 wrist viewers                                    B2 wrists 360p30 × 2 (H.264)
A3 50 Hz state viewer, config query                          B3 control / watchdog / state
       | local Zenoh pub/sub + query                                | local Zenoh pub/sub + query
[Zenoh router]—[C++ operator bridge]                     [C++ robot bridge]—[Zenoh router]
                         |                                         |
                         +—— encrypted outbound sessions* ——+      |
                           via public relay* (no inbound at warehouse)
                             ▲ UDP best effort: video/state robot→operator,
                               motion operator→robot
                             ▲ reliable ordered: TCP / QUIC / KCP by test mode

*Relay, encrypted deployment tunnel, Wi-Fi roaming and LTE failover are PROPOSED;
 the BUILT testbed uses direct veth/ns routing (10.200.1.1 ↔ 10.200.1.2).
```

**Per-link traffic plan (decimal Mbit/s, application allocation including a reserved wire-overhead allowance).** At **8 Mbit/s robot→operator**, allocate head **4.6**, left wrist **1.2**, right wrist **1.2**, state/queries/ACK **0.3**, framing/tunnel/control reserve **0.7** = **8.0**. At **2 Mbit/s**, prioritize head **1.35**, wrist streams **0.12 each**, essential state/replies **0.15**, wire-overhead/control reserve **0.26** = **2.00**. Wrist streams are first degraded to very low rate or suppressed; preserve head and essential state. All figures are **design allocations, not encoder measurements**; byte-counted bridge shaping and ≥80% *intact head frames within 200 ms* at 2 Mbit/s still require Task 2 validation. Control commands flow **operator→robot**, separately: 100 B × 100 Hz × 8 = **0.080 Mbit/s payload**, with a proposed **0.15 Mbit/s wire budget**; 50 Hz state gets priority within the robot uplink. Actual rate depends on fragmentation/headers and codec outputs. **[Built]** UDP real-time path + configurable reliable ordered lane; **[Not yet demonstrated]** total egress shaping at the required 8→2 Mbit/s cycle.

## 2. Timing and safety design

| Path | Calculated design envelope (not measured) | Acceptance rule |
|---|---|---|
| Camera→screen | capture/encode **30** + fragment/bridge **10** + nominal WAN **45** + decode/display **35** + jitter allowance **60** = **180 ms** | ≥80% intact head frames **≤200 ms** during 2 Mbit/s budget |
| Hand→motion | capture/publish **5** + bridge **5** + nominal WAN **45** + B3 validation **5** + simulated actuation **10** = **70 ms** | Drop age >150 ms; never apply an older sequence; stop if no fresh input for 300 ms |
| E-stop command→effect | input **5** + priority transport **10** + WAN **45** + controller effect **10** + recovery reserve **80** = **150 ms** | **≤200 ms** under load; test separate from ACK latency |

These are **proposed engineering budgets**; the WAN component is an allowance for a nominal operating state, not a promise during the specified 280 ms worst-case RTT or link outage. A hard ≤200 ms effect during a genuine network blackout **cannot be guaranteed by a remote transport**; local watchdog, independent safe-stop behavior, and explicit reporting of unachievable conditions are required. **[Built]** B3 validates monotonic sequence/session IDs and 150 ms command age; persistent E-stop command IDs, duplicate checks, and a 280 ms watchdog trigger target the 300 ms stop requirement. **[Unverified]** repeated <200 ms E-stop effects, exactly-once effects during restarts, and physical actuator timing.

## 3. Roaming, backup and outage timelines — proposed deployment

**Connectivity:** two overlapping, independently powered 5 GHz warehouse APs (802.11k/v assisted roaming; 802.11r only if client/security compatibility tested), adequate signal and channel planning, robot-initiated outbound tunnel to public relay, and LTE backup with pre-established warm standby. The robot never requires unsolicited inbound connections. Avoid assuming handover is lossless: packets can be dropped/reordered and stale buffered controls must be rejected. **[Not built]** roaming, LTE switching, relay and internet deployment.

| After disruption | 2 s outage | 30 s outage |
|---|---|---|
| **0 ms** | Link telemetry detects packet/reply gaps; robot's last valid command remains subject to age check | Same |
| **150 ms** | Any arriving command older than threshold rejected | Same |
| **≤300 ms** | Local motion watchdog demands stop independently of the network | Same; remain stopped |
| **~0.3–2 s** | Wi-Fi roam/reconnect or switch to warm LTE; re-authenticate session; flush obsolete commands; resume video at keyframe | LTE may take over; retry with bounded backoff; continue fail-safe; no old command replay |
| **At 2 s** | On restored link, new session/fresh commands and fresh frames resume; **<1 s bridge-restart recovery is a separate acceptance test** | Still stopped without usable link |
| **At 30 s** | Not applicable | Re-establish authenticated control authority, obtain fresh state, require deliberate enable/reset as policy, then resume streams |

The sequence shows **intended** behavior, not measured failure-detection or reconnection durations. An outage longer than 200 ms makes remote E-stop delivery within 200 ms impossible; the local stop watchdog handles loss of ongoing control, but it is **not a substitute** for a separate safety-rated emergency-stop channel in a physical robot.

## 4. Security and keys

**Threats:** injection/replay of motion or E-stop/reset commands, forged robot state/video, man-in-the-middle, stolen robot credentials, compromised relay, traffic flooding. **Defences [Proposed]:** authenticate each robot/operator identity; enforce per-topic direction and permissions; protect bridge traffic with mutual-authenticated TLS 1.3/QUIC or a WireGuard tunnel (including UDP/KCP traffic); pin trusted certificates/peer keys, rotate/revoke credentials, bound replays with session+sequence+freshness, isolate control traffic from bulk video; keep controller fail-safe if authentication fails. **Keys:** device private keys in robot OS-protected secrets or TPM when available; operator keys in platform keystore; relay holds only its own service credentials, not controller authority. **Lab caveat:** QUIC client certificate verification is disabled in the current isolated testbed and must be enabled for deployment; the standalone KCP path is not authenticated.

## 5. Bill of materials and choices

| Product / role | Location | Budgetary cost and source | Reason / status |
|---|---|---|---|
| Linux mini-PC with Zenoh + C++ bridge | Operator and robot | **Reused in testbed; procurement TBD** | Existing compute; actual SKU/cost not supplied **[Built as host processes]** |
| 3 H.264-capable cameras (720p head; 360p wrists) | Robot | **TBD from actual camera SKU** | Simulation presently generates deterministic encoded data **[Mock only]** |
| Ubiquiti UniFi U6+ Wi-Fi 6 AP (two) | Warehouse | **€89 each**, EU vendor listing | Planned overlapping AP coverage **[Proposed]** |
| Teltonika RUT241 LTE router | Robot | **~€184**, Oct 2026 German price comparison | Proposed backup WAN; verify radio/operator suitability **[Proposed]** |
| Hetzner CAX11 relay VM | Public/cloud | **€5.99/month** excl. VAT, published 2026 tariff; public IPv4/data extra as applicable | Low-cost proposed publicly reachable endpoint; verify capacity **[Proposed]** |
| Zenoh, C++ bridge, Linux `tc`, simulation | Both sites | Open-source software; hosting/integration excluded | **[Built]** local testbed |

**Price references:** [U6+ EU store](https://eu.store.ui.com/eu/en/products/u6-plus); [RUT241 Germany price comparison](https://geizhals.de/teltonika-rut241-lte-wlan-router-rut241034000-a3820183.html); [Hetzner June 2026 tariffs](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/). Hardware BoM is **not a complete robot purchase estimate**; power, mounting, SIM subscription, switches, cameras and labor require quotations.

## 6. Three trade-offs and update from measurement

1. **All-TCP/all-KCP reliability vs. mixed lanes:** rejected one shared ordered data path for motion/video after preliminary all-KCP queue buildup under impairment. **Chosen:** UDP for fresh state/video/motion, reliable ordered TCP/QUIC/KCP for safety/config. **Measured:** office tests completed 2,250/2,250 head frames and 75/75 queries in each hybrid mode; no protocol winner proven.
2. **Direct robot inbound vs. outbound relay:** direct inbound rejected because warehouse IT blocks ports. **Chosen for production design:** robot-initiated authenticated outbound connection via relay; **not implemented** in local namespace testbed.
3. **Maximum all-camera quality vs. bounded head usability:** keeping all streams at full rate at 2 Mbit/s rejected. **Chosen:** prioritize head and state, sacrifice wrist bitrate first; actual ≤2 Mbit/s shaping and timely-frame threshold **still unverified**.

**Measured Task 3 network checks:** office LAN RTT **0.049 ms**, **0%** of 300 ICMP probes lost; inter-city mean RTT **20.531 ms**, **0.24%** of 5,000 round trips lost with **0.1% configured per direction**; warehouse mean RTT **~92.19 ms**, total loss **~3.65% including blackouts**, with measured extrema near **41–276 ms**. Warehouse burst-loss baseline and exact blackout duration have not been independently isolated. Figures from the virtual testbed do not prove physical link/failover behavior. Re-evaluate bitrate allocations, per-hop budgets and transport preference after the Task 2 bandwidth/E-stop/recovery acceptance tests.
