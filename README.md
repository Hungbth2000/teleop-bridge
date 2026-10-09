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

## Status

Initial repository setup. Implementation and testing are pending.

## Requirements

See the original coding challenge for the complete requirements.

## Build and Run

Build and execution instructions will be added as the implementation develops.
