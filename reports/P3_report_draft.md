# Person 3 Report Draft

## 6. Node failure and availability

We evaluated Cassandra 5.0.8 on a three-node cluster with replication factor 3.
Each Exp 3 variant was run three times with live QUORUM workload and concurrent
ONE, QUORUM, and ALL read/write probes. Runs 3a and 3b lasted 120 seconds; run
3c lasted 180 seconds. A sudden failure was injected after 15 seconds and
lasted 20 seconds. Variant 3a killed one node, 3b killed two nodes, and 3c
compared a graceful stop/restart with a kill/restart of one node.

| Variant | Probe consistency | Successful / attempted operations | Success |
|---|---:|---:|---:|
| 3a, one node killed | ONE | 2,880 / 2,880 | 100.00% |
| 3a, one node killed | QUORUM | 2,880 / 2,880 | 100.00% |
| 3a, one node killed | ALL | 1,713 / 2,096 | 81.73% |
| 3b, two nodes killed | ONE | 2,878 / 2,879 | 99.97% |
| 3b, two nodes killed | QUORUM | 1,700 / 2,080 | 81.73% |
| 3b, two nodes killed | ALL | 898 / 1,690 | 53.14% |
| 3c, graceful stop then kill | ONE | 4,318 / 4,318 | 100.00% |
| 3c, graceful stop then kill | QUORUM | 4,318 / 4,318 | 100.00% |
| 3c, graceful stop then kill | ALL | 2,314 / 3,099 | 74.67% |

These totals cover each entire experiment, including healthy periods before,
between, and after faults; they are not fault-window-only availability rates.
With one replica unavailable, the probes retained ONE and QUORUM service while
ALL operations were affected. With two replicas unavailable, QUORUM and ALL
operations failed during the outage, while ONE was almost always successful.
All runs ended with the three nodes reporting Up/Normal.

The mean peer detection time for a killed node was 19.24 seconds in 3a. In
3b, six kill events across the three repetitions averaged 19.37 seconds. In
3c, a graceful stop was detected in an average of 0.67 seconds, compared with
20.53 seconds for a kill. The graceful shutdown notification was therefore
observed substantially sooner than gossip detection after a sudden process
failure.

## 7.3. Network partition and reconciliation

Exp 5 partitioned cass3 from the Docker network while leaving its container
running. The majority and minority status views showed the partition, and
gossip detected the remote node as Down from both sides. Across three
repetitions, cass1 (majority view) detected cass3 after 19.34 seconds on
average; cass3 (minority view) detected cass1 after 18.84 seconds on average.

The direct consistency checks produced the expected outcomes in all three
runs:

* A QUORUM write from the minority failed with `Cannot achieve consistency
  level QUORUM` (one replica alive where two were required).
* A ONE write from the minority succeeded.
* A QUORUM write from the majority succeeded.
* After healing, an ALL read returned `last_seq = 222` and
  `updated_by = majority`. The majority write used a timestamp later than the
  minority write, so this result confirms Cassandra's timestamp-based
  last-write-wins reconciliation for this test.

The concurrent availability probe also recorded intermittent failures at
different consistency levels during these runs. Its per-level operation counts
vary because operations can block while a replica is unreachable; these counts
should be interpreted alongside the timestamped per-operation CSVs rather than
as equal-sized, fixed-rate samples. In particular, the run logs report many
scheduled workload operations starting more than 50 ms late under the chosen
load. The measured result is still useful for observing failures and recovery,
but the requested workload rate should not be presented as the achieved rate.

## 8. CAP, PACELC, and failure-state analysis

The results illustrate why Cassandra's consistency level matters during a
partition; describing Cassandra as unconditionally “AP” or “CP” would obscure
the operation-level behavior. On the minority side, a ONE write was accepted
by an available replica, favoring availability, while a QUORUM write was
rejected because the minority could not satisfy the required acknowledgements.
The majority retained enough replicas to accept a QUORUM write. This is the
CAP consistency/availability trade-off under the tested partition.

Under PACELC, when a partition exists the system must trade consistency against
availability for a request; the minority ONE and QUORUM results demonstrate
that choice. Elsewhere, when the cluster is operating normally, consistency
levels impose different coordination and replica requirements, and therefore
different latency/availability characteristics. These experiments recorded
operation outcomes and latencies, but did not isolate a controlled
no-partition latency comparison, so no numerical PACELC latency claim is made.

Reconciliation is also conditional on the write timestamps: the test
deliberately assigned the majority write a higher timestamp, and the post-heal
ALL read returned it. The result demonstrates the configured last-write-wins
rule, not a general guarantee that a majority-side value always wins.

### Evidence and integration notes

Raw per-operation measurements are under `results/raw/exp3/` and
`results/raw/exp5/`. Per-run status, detection, assertion, and recovery output
is under `results/logs/exp3/` and `results/logs/exp5/`. The report still needs
to be merged into the group's final report, with the other members' sections
and P4's availability timeline/figure.

## Five-minute presentation outline

1. **Setup and method (45 seconds):** State the three-node, RF=3 Cassandra
   setup; describe one-node and two-node failures, graceful stop versus kill,
   and the active consistency-level probes.
2. **Node failures (75 seconds):** Explain that ONE and QUORUM remained
   available with one failed replica, while ALL was affected. With two nodes
   down, QUORUM and ALL became unavailable during the fault. Highlight the
   roughly 19-second kill-detection time versus less than one second for a
   graceful stop.
3. **Partition result (90 seconds):** Show the running-but-disconnected
   minority node. Its QUORUM write was rejected, its ONE write succeeded, and
   the majority QUORUM write succeeded. After healing, the ALL read returned
   the higher-timestamp majority value.
4. **CAP/PACELC interpretation (60 seconds):** Emphasize that the chosen
   consistency level determines the observed consistency/availability trade-off
   during a partition. Avoid labeling Cassandra as unconditionally AP or CP;
   note that this experiment did not isolate a controlled latency-only
   comparison for PACELC's else case.
5. **Takeaway and caveat (30 seconds):** Summarize automatic detection and
   recovery, then note that some workload operations started late under the
   selected load, so requested rate is not the achieved rate.
