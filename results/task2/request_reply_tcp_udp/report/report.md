# Task 2.4 — Request/Reply Validation

## Normal workload

Duration: 75 seconds.

Workload: three camera streams, motion commands, state updates,
and A3 configuration queries at one-second intervals.

| Metric | Result |
|---|---:|
| Queries sent | 75 |
| Successful queries | 75 |
| Failed queries | 0 |
| Zero-reply queries | 0 |
| Duplicate-reply queries | 0 |
| Extra replies | 0 |
| Mean first-reply latency | 5.404 ms |
| p50 first-reply latency | 5.136 ms |
| p95 first-reply latency | 10.535 ms |
| p99 first-reply latency | 11.059 ms |
| Maximum first-reply latency | 11.111 ms |

Result: PASS.

Evidence:
- evidence/query_workload.csv
- evidence/three_camera_runner.log
- evidence/three_camera_logs/
- report/summary.json

## Concurrent queries

Eight simultaneous configuration queries were issued.

| Metric | Result |
|---|---:|
| Requests | 8 |
| Successful requests | 8 |
| Failed requests | 0 |
| Missing replies | 0 |
| Extra replies | 0 |
| Minimum latency | 2.83 ms |
| Maximum latency | 5.26 ms |

Result: PASS.

Evidence:
- fault_tests/concurrent/concurrent_queries.log

## Timeout handling

The B3 query handler was configured with a 4000 ms artificial
response delay. A3 used a 3000 ms query timeout.

| Query | Valid replies | Completion |
|---|---:|---:|
| 1 | 0 | 3043.395 ms |
| 2 | 0 | 3080.824 ms |
| 3 | 0 | 3019.088 ms |

The client remained operational, recorded each failed request,
and completed the experiment normally.

Result: PASS.

Evidence:
- fault_tests/timeout/query_timeout.csv
- fault_tests/timeout/a3_timeout.log
- fault_tests/timeout/b3_delayed.log

## Limitations

The normal query workload counts valid replies whose JSON payload
identifies node B3. A zero-valid-reply result may represent timeout,
invalid payload, or another query failure; it does not by itself
identify the underlying cause.

The fault test intentionally introduces a response delay exceeding
the client timeout. Its timings are consistent with expiration of
the 3000 ms timeout, but the server log should be retained to
corroborate the injected delay.

The concurrent test covers eight simultaneous requests, not a
large-scale saturation test.

## Conclusion

Task 2.4 passed the tested scenarios: 75 successful queries under
concurrent media and control load, eight successful simultaneous
queries, zero observed duplicate replies, and clean timeout
handling during delayed server responses.
