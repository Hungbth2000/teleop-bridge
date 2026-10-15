# Task 3 — Real Network Testing

## Objective

Evaluate the hybrid TCP/UDP teleoperation bridge under three simulated network conditions using Linux `tc netem`. The goal is to verify both the network conditions and the communication performance of the application.

The experiments cover three camera streams, fast motion commands, and request/reply communication.

## Test Environment

The experiments were performed in WSL2 using two Linux network environments:

- **Operator:** Default namespace, `veth-teleop-op`, IP `10.200.1.1`
- **Robot:** `teleop-robot` namespace, `veth-teleop-rb`, IP `10.200.1.2`

The virtual Ethernet configuration can be created or verified using:

```bash
sudo bash scripts/setup_network.sh
```

The application uses two Zenoh routers connected by the custom bridge. The evaluated bridge configuration is hybrid TCP/UDP.

## Network Scenarios

| Scenario | Configured conditions |
|---|---|
| Office LAN | No artificial impairment |
| Inter-city | 10 ms ± 2 ms delay and 0.1% loss per direction |
| Warehouse Wi-Fi | 45 ms ± 25 ms delay per direction, Gilbert–Elliott burst loss, periodic delay spikes, and approximately 500 ms blackout every 30 seconds |

The impairment scripts are `experiments/intercity_network.py` and `experiments/warehouse_network.py`.

## Network Validation

| Measurement | Office LAN | Inter-city | Warehouse Wi-Fi |
|---|---:|---:|---:|
| Observed minimum RTT | 0.020 ms | 16.937 ms | 41.0 ms* |
| Observed mean RTT | 0.049 ms | 20.416 ms | 91.362 ms* |
| Observed maximum RTT | 0.340 ms | 24.552 ms | 273.0 ms* |
| Observed aggregate ICMP loss | 0% | 0.24% | 3.133% |

*Warehouse corrected RTT statistics exclude four anomalous zero-millisecond samples. The raw measurements are retained.*

The warehouse probe overlapped three recorded blackouts lasting 509.841 ms, 526.587 ms, and 510.107 ms.

The background loss model was configured to produce approximately 1% bursty loss per direction, but this component was not independently isolated from blackout loss. The observed 3.133% is the aggregate ICMP round-trip loss.

## Application Results

The following video results count matched transmitted and received frames delivered within 200 ms.

| Metric | Office LAN | Inter-city | Warehouse Wi-Fi |
|---|---:|---:|---:|
| Head good-frame delivery | 100.00% | 99.20% | 96.22% |
| Left wrist good-frame delivery | 97.38% | 99.69% | 97.07% |
| Right wrist good-frame delivery | 97.33% | 99.78% | 97.29% |
| Head good-frame latency p95 | 23.211 ms | 52.061 ms | 82.016 ms |
| Left wrist latency p95 | 13.711 ms | 38.601 ms | 72.498 ms |
| Right wrist latency p95 | 18.516 ms | 39.313 ms | 71.700 ms |
| Configuration query success | 75/75 | 75/75 | 75/75 |

The office and inter-city video results were extracted from archived runs using matching frame identifiers. Their precise network-profile and transport provenance was not independently recorded. Warehouse results come from a clean 75-second retest, with matching TX/RX records preserved.

These measurements demonstrate intact frame reception by the application, not independent successful H.264 decoding.

## Warehouse Motion Performance

The clean warehouse trial produced 7,365 received motion-command records from one sender session.

| Measurement | Result |
|---|---:|
| Applied commands | 4,380 |
| Rejected due to sequence ordering | 2,985 |
| Missing sequences within observed sequence range | 200 |
| Duplicate sequence records | 0 |
| Stale commands applied | 0 |
| Applied-command latency mean | 39.165 ms |
| Applied-command latency p95 | 60.751 ms |
| Applied-command latency p99 | 68.886 ms |
| Applied-command latency maximum | 139.232 ms |

The rejection mechanism prevented commands with older sequence numbers from being applied after newer ones. However, the high number of sequence rejections may affect motion smoothness.

## Recovery Following Warehouse Blackouts

The 75-second warehouse video workload overlapped two network blackouts.

| Measurement | Blackout 1 | Blackout 2 |
|---|---:|---:|
| Blackout duration | 520.709 ms | 510.461 ms |
| First applied motion after blackout | 29.773 ms | 26.245 ms |
| Age of first recovered command | 26.741 ms | 24.510 ms |

Fresh motion commands resumed being applied shortly after both blackouts ended.

These results establish communication recovery in the simulated controller. They do not independently establish actuator response or watchdog and E-stop behavior during the interruption.

## Conclusions

The hybrid TCP/UDP bridge maintained high on-time video delivery in all three measured scenarios. Warehouse Wi-Fi increased latency and frame loss, but the clean retest still delivered approximately 96–97% of generated video frames within 200 ms.

Fast motion communication also recovered quickly after the two observed warehouse blackouts. No stale commands were applied in the preserved B3 session.

The system demonstrated a trade-off between preserving fresh motion and applying every generated control update. Under warehouse impairment, many received commands were rejected because they arrived behind a newer accepted sequence.

The experiment supports the use of hybrid TCP/UDP for this prototype, while identifying further work on motion smoothness, blackout safety validation, and network-loss characterization.

## Limitations and Evidence

The experiment used Linux network emulation rather than physical Wi-Fi hardware. Warehouse background burst loss was configured but not measured separately from blackout-related loss. Office and inter-city archived application trials have limited configuration provenance. E-stop and watchdog behavior during warehouse blackouts was not independently demonstrated.

Raw and derived evidence is retained under `results/task3/real_network/`, including the clean warehouse retest, network probe, blackout controller logs, filtered B3 records, and recovery summaries.

### Reproducible Video Evidence

The office LAN, inter-city, and warehouse video datasets originally contained accumulated records from multiple experiments. To avoid mixing runs, the selected TX and RX frames were extracted by their exact run IDs and preserved under `results/task3/real_network/selected_video_runs/`.

Each camera has separate `tx.csv` and `rx.csv` files. The accompanying `manifest.json` records the run ID, original source paths, frame counts, and SHA-256 checksums.

To reproduce the video comparison after cloning the repository:

```bash
python experiments/analyze_task3_video.py
```

The analyzer verifies evidence checksums and matches transmitted and received frames by stream ID and frame ID. A frame is counted as good only if its measured capture-to-reception latency is between 0 and 200 ms.

The packaging script `experiments/package_task3_video.py` documents how the selected evidence was extracted from the original cumulative logs. Re-running the packaging script requires those original source files; reproducing the reported metrics does not.

The archived office and inter-city runs have matching TX/RX evidence, but their exact active network-profile and bridge-transport configurations were not independently recorded. The warehouse results come from the clean 75-second retest and are supported by separate impairment and blackout evidence.