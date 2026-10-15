# Task 2.5 — Bridge Restart Recovery

The operator and robot bridges were tested separately.
Each bridge was killed with SIGKILL, kept offline for
approximately five seconds, then relaunched.

| Metric | Operator | Robot |
|---|---:|---:|
| Downtime | 5001.528 ms | 5004.456 ms |
| Head video recovery | 123.661 ms | 51.088 ms |
| Left wrist recovery | 124.156 ms | 44.407 ms |
| Right wrist recovery | 138.945 ms | 23.127 ms |
| Fresh motion recovery | 117.282 ms | 20.440 ms |
| Full recovery | 138.945 ms | 51.088 ms |

Both trials recovered all three decoded video streams
and the fresh, applied motion-command path.

Recovery is measured from replacement-process launch.
The deliberate five-second downtime is reported separately.

A good frame is successfully decoded, captured after
restart, and has capture-to-decode latency <= 200 ms.
A recovered motion command is created after restart,
is fresh (age 0–150 ms), and is applied at B3.

This validates the two observed restart trials, not a
statistical worst-case recovery bound.

Evidence:
- operator_bridge_restart/recovery_summary.json
- robot_bridge_restart/recovery_summary.json
- Each trial's restart_events.json, decoded-frame CSVs,
  motion_rx.csv, bridge.log, and runner.log
