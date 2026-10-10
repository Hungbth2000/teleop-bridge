# Remote Teleoperation Bridge — Architecture

## 1. Overview

The system connects an operator in Stuttgart with a robot
in a warehouse in the Netherlands.

Both sites communicate locally through zenoh routers.
A C++ bridge at each site forwards selected traffic
between the routers over the WAN.

The bridge separates traffic into different classes
based on latency, reliability, and bandwidth requirements.

## 2. Traffic Classes

| Class | Rate | Delivery policy |
|---|---|---|
| Fast commands | 100 Hz | Latest valid command wins |
| Reliable commands | Event-driven | Ordered, exactly-once application |
| Robot state | 50 Hz | Latest state wins |
| Video | 30 fps per camera | Complete frames or drop |
| Queries | On demand | One reply or timeout |

## 3. Initial Transport Design

- UDP-style datagrams for fast commands, state, and video.
- Reliable streams for safety commands and queries.
- Separate priority queues and bandwidth scheduling.
- Outbound-initiated connectivity for the warehouse.
- Authentication and encryption for WAN traffic.

## 4. Safety Requirements

- Reject commands with non-increasing sequence numbers.
- Reject commands older than 150 ms.
- Stop robot motion after 300 ms without fresh commands.
- Prioritize emergency-stop messages over video traffic.
- Deduplicate reliable commands using unique command IDs.

## 5. Open Questions

- Direct transport versus relay or VPN.
- UDP/TCP versus QUIC.
- Video encoding and bandwidth allocation.
- Clock synchronization and timestamp validation.
- Reliable command persistence across restarts.
- Recovery behavior after network outages.


