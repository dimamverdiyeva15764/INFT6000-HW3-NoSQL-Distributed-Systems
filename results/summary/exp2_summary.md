# Experiment 2 - consistency tuning: summary

Generated from 45 runs (513,202 logged operations) in `results/raw/exp2/`.

## Fixed-rate grid (latency of successful operations, repetitions pooled)

| mode | CL | runs | ops | p50 ms | p95 ms | p99 ms | mean ms | ok ops/s | sd | error % | errors |
|---|---|---|---|---|---|---|---|---|---|---|---|
| write | ONE | 3 | 36000 | 1.47 | 1.96 | 2.20 | 1.42 | 200.02 | 0.00 | 0.00 |  |
| write | QUORUM | 3 | 36000 | 1.86 | 2.49 | 2.75 | 1.83 | 200.02 | 0.00 | 0.00 |  |
| write | ALL | 3 | 36000 | 1.98 | 2.64 | 2.90 | 1.94 | 200.02 | 0.00 | 0.00 |  |
| read | ONE | 3 | 36000 | 1.98 | 2.71 | 3.06 | 1.96 | 200.02 | 0.00 | 0.00 |  |
| read | QUORUM | 3 | 36000 | 2.44 | 3.21 | 3.59 | 2.43 | 200.02 | 0.00 | 0.00 |  |
| read | ALL | 3 | 36000 | 2.48 | 3.23 | 3.61 | 2.45 | 200.02 | 0.00 | 0.00 |  |
| mixed | ONE | 3 | 36000 | 1.69 | 2.72 | 3.09 | 1.74 | 200.01 | 0.00 | 0.00 |  |
| mixed | QUORUM | 3 | 36000 | 2.14 | 3.31 | 3.73 | 2.20 | 200.02 | 0.00 | 0.00 |  |
| mixed | ALL | 3 | 36000 | 2.19 | 3.28 | 3.70 | 2.23 | 200.02 | 0.00 | 0.00 |  |

## Closed-loop saturation (mixed)

| CL | ops | ok ops/s | p50 ms | p99 ms | error % |
|---|---|---|---|---|---|
| ONE | 45661 | 1522.53 | 2.96 | 12.41 | 0.00 |
| QUORUM | 42731 | 1424.74 | 3.46 | 12.15 | 0.00 |
| ALL | 40810 | 1360.68 | 3.64 | 12.30 | 0.00 |

## Freshness probes

| W | R | R+W | R+W>N | probes | stale | stale % | read p50 ms |
|---|---|---|---|---|---|---|---|
| ONE | ONE | 2 | False | 6000 | 0 | 0.00 | 1.76 |
| ONE | QUORUM | 3 | False | 6000 | 0 | 0.00 | 2.12 |
| QUORUM | QUORUM | 4 | True | 6000 | 0 | 0.00 | 1.94 |
| ALL | ONE | 4 | True | 6000 | 0 | 0.00 | 1.69 |
| ONE | ALL | 4 | True | 6000 | 0 | 0.00 | 2.12 |

## Experiment 1 baseline (mixed, QUORUM, 200 ops/s)

ops 12,000, ok 12,000, errors 0.000 %, throughput 200.0 ops/s, p50 2.05 ms, p95 3.26 ms, p99 3.71 ms

## Observations (generated from the data)

- Median latency at ONE/QUORUM/ALL was write 1.47/1.86/1.98 ms; read 1.98/2.44/2.48 ms; mixed 1.69/2.14/2.19 ms. In every mode the median rose monotonically from ONE to ALL, as expected because the coordinator waits for 1, 2 and 3 replica responses respectively.
- The tail widens more than the median: write p99 was 2.20 ms at ONE and 2.90 ms at ALL (1.3x), because ALL waits for the slowest of the three replicas while ONE only needs the fastest.
- All 324,000 operations of the fixed-rate grid succeeded.
- Every fixed-rate cell sustained its target rate, so latency differences are not caused by back-pressure.
- Closed-loop saturation throughput was 1,523, 1,425 and 1,361 ops/s at ONE, QUORUM and ALL (11% lower at ALL than at ONE). With RF = N = 3 every replica applies every write whatever the CL, so for writes only the client's waiting time differs; a read at QUORUM or ALL additionally sends one or two digest requests, which adds server work. Because the Python client itself is CPU-bound near saturation, these values are a lower bound on cluster capacity.
- Pairs with R+W<=N returned 0 stale value(s) in 12,000 probes (0.00%); pairs with R+W>N returned 0 in 18,000 probes, consistent with the quorum-overlap guarantee. No staleness was observed even without overlap: on a healthy single-host cluster the replica mutations arrive long before the client's next request, so the inconsistency window is shorter than one client round trip. Staleness becomes visible once a replica misses writes (Exp 4b, Exp 5).
