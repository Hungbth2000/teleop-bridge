# Task 2.1 — Camera good-frame results

Successful frame = decoder output within 200 ms of capture; denominator = all captured frames.

| Camera | Budget | Captured | Good | Late | Missing/not decoded | Good % | p95 (ms) | Max (ms) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| head | 8 | 1453 | 1453 | 0 | 0 | 100.0 | 13.364 | 33.452 |
| head | 2 | 797 | 797 | 0 | 0 | 100.0 | 48.074 | 82.877 |
| head | all | 2250 | 2250 | 0 | 0 | 100.0 | 25.442 | 82.877 |
| left | 8 | 1451 | 1451 | 0 | 0 | 100.0 | 6.489 | 11.702 |
| left | 2 | 799 | 774 | 0 | 25 | 96.871 | 71.458 | 115.607 |
| left | all | 2250 | 2225 | 0 | 25 | 98.889 | 10.828 | 115.607 |
| right | 8 | 1451 | 1451 | 0 | 0 | 100.0 | 6.33 | 23.518 |
| right | 2 | 799 | 773 | 0 | 26 | 96.746 | 64.24 | 122.202 |
| right | all | 2250 | 2224 | 0 | 26 | 98.844 | 19.172 | 122.202 |

**Head at 2 Mbit/s:** PASS (797/797 good).

Limitations: decoder output readiness is not physical display; CRC32 + decode do not prove pixel-perfect equality with a deterministic reference. Budget compliance including wire overhead requires separate network-byte measurement.
