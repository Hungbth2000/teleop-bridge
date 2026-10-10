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

### Bandwidth Management

The robot's outbound traffic is limited to:

- **Normal operation:** Maximum 8 Mbps.
- **Degraded operation:** Maximum 2 Mbps for 15 seconds per minute.

The bridge uses priority-aware scheduling, bounded queues, and a rate limiter. During degraded operation, wrist-camera traffic is reduced first to preserve head-camera delivery and robot state updates.

The requirement is for at least 80% of head-camera frames to arrive intact within 200 ms under the 2 Mbps limit. Compliance remains to be demonstrated in testing.

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

### Security

- QUIC uses TLS 1.3 for encrypted and authenticated transport.
- Bridges authenticate the public relay.
- Access to bridge credentials and private keys is restricted.
- The robot controller independently validates command sequence numbers and timestamps.
- The robot stops if no fresh movement command arrives within 300 ms.
- The relay terminates the two QUIC connections; additional end-to-end protection is required if the relay must not access application payloads.

### Implementation Status

This document describes the proposed Task 1 architecture. Transport performance, failover timing, bandwidth compliance, command reliability, and video latency are design targets that will be evaluated during Tasks 2 and 3.
