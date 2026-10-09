# Design Assumptions and Constraints

## System
- Operator site: Stuttgart
- Robot site: Netherlands warehouse
- Warehouse does not allow inbound port forwarding
- Both sites use local zenoh routers
- Bridge handles communication between the sites

## Traffic
- Fast operator commands: 100 Hz
- Reliable commands: ordered, exactly-once application
- Robot state: 50 Hz
- Head camera: 1280x720, 30 fps
- Two wrist cameras: 640x360, 30 fps each
- Queries: exactly one reply or explicit timeout

## Safety
- Never apply an older fast command after a newer one
- Reject fast commands older than 150 ms
- Stop robot after 300 ms without fresh commands
- Emergency stop must take effect within 200 ms

## Network
- Normal bridge budget: 8 Mbps
- Reduced bridge budget: 2 Mbps
- Bridge restart recovery target: 1 second
- Unreliable warehouse Wi-Fi
- Cellular failover is considered in the design

## Open Design Questions
- Which transport should each traffic class use?
- How should exactly-once command application be implemented?
- How should video be compressed and prioritized?
- How should bandwidth be enforced?
- How will clocks be synchronized for command-age measurements?
- How should session recovery and reconnection work?
- How should encryption and authentication be handled?
