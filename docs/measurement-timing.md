# Measurement timing contracts

`metadata.timing_scope` identifies the meaning of a report's measured duration.
The version is part of the identifier. Equal field names or package versions
do not establish equal timing boundaries. A change to those boundaries requires
a new scope identifier and an explicit compatibility decision.

This contract does not replace correctness, validity, provenance, streaming
condition fingerprints or raw-evidence checks. It does not measure the cost of
individual transport, allocation, GIL or scheduling operations.

## Current scopes

| Suite or profile | Scope | Measured wall interval |
| --- | --- | --- |
| requests, compressed-response | `requests-load-only-v2` | The measured load dispatcher inside ResourceSampler, including scheduling, requests, response validation and progress work. |
| one-upstream | `one-upstream-load-only-v2` | The measured one-upstream load dispatcher inside ResourceSampler, including per-request work selected by the case. |
| proxy-connect | `proxy-connect-load-only-v2` | The measured proxy load dispatcher inside ResourceSampler, including client construction and close when required by a fresh-client case. |
| resource-backpressure | `resource-backpressure-load-only-v2` | The measured load dispatcher inside both ResourceSampler and TransportStatsSampler. Recovery checks are outside the interval. |
| client-creation | `client-creation-operation-v1` | The entire selected lifecycle operation. It can include construction, requests, internal snapshots and close. External snapshots and preceding garbage collection are outside the interval. |
| request-builder | `request-builder-load-only-v1` | Sequential build/validation iterations and optional send-prepared work. The sync interval is measured inside its worker; the async interval is inside ResourceSampler. |
| response-streaming, default profile | `load-only-v2` | The streaming load dispatcher, including scheduling, consumption, integrity checks and progress work. |
| response-streaming, lifecycle profile | `lifecycle-round-load-v1` | The sum of measured round intervals around submission/wait or gather/consume. Preparation and result collation between rounds are excluded. |
| response-streaming, async-bytes profile | `load-only-incremental-sha256-v1` | The existing streaming load interval, including scheduling, iteration, incremental hashing, observations, consumer delay and stream context exit. Digest finalization/verdict, replay and report I/O are outside it. |

For the load-only ordinary scopes, warmup finishes before sampler entry. The
wall clock starts after all samplers have entered and stops before they exit.
Outer client statistics and close are outside that interval. Client close
inside the workload remains included when the scenario measures it.

The timing fix leaves sampling and cleanup in place. Sampler setup and teardown
still execute; they are excluded from load duration. Sampler peaks can include
their final observation after the timed load, so their boundaries are not
identical to the wall interval. There is no new performance baseline in this
change, and preserved research artifacts are not rewritten.

## CPU and resource boundaries

Requests and compressed-response already expose `process_cpu_s`. Their
`time.process_time()` probes now bracket the same logical load as the wall
clock, inside ResourceSampler. The CPU probes enclose the wall-clock probes;
they are not atomic simultaneous readings. They exclude warmup, sampler entry
and exit, client statistics and outer close. They still include sampler CPU
used during the load and all other work in the benchmark process.

The ordinary local HTTP server and client share a process, and async variants
also share an event loop. Process CPU, RSS, threads and descriptors therefore
describe that combined system. Removing sampler entry/exit from duration does
not isolate client CPU or prove an improvement in the installed HTTP client.
This task adds no new CPU measurements to suites that did not expose them.

The async-bytes profile retains separate client/server CPU probes. Those probes
bracket a wider interval than its wall load, including the reported boundary
probe span and profiler start/stop where applicable. Their existing scope and
resolution limitations remain in force. They are not converted to the ordinary
request CPU contract.

## Reading and comparing older reports

Loading a JSON report remains possible without timing metadata. Comparison and
isolated merging require a supported, internally consistent scope. A missing
scope is unknown; it is not inferred from a suite name, date, package version
or the current implementation.

Explicit historical scopes are supported for the affected old paths:

| Suite | Historical scope |
| --- | --- |
| requests, compressed-response | `requests-sampler-inclusive-v1` |
| one-upstream | `one-upstream-sampler-inclusive-v1` |
| proxy-connect | `proxy-connect-sampler-inclusive-v1` |
| resource-backpressure | `resource-backpressure-sampler-inclusive-v1` |
| default response-streaming | `legacy-sampler-v1` |

These historical scopes include sampler entry/exit. The request CPU probes
also included those phases. The resource path included both samplers. Equal,
explicitly identified historical scopes can be compared with each other,
subject to all existing validity checks. Historical and corrected scopes
cannot be compared with each other.

Existing ordinary streaming reports can identify their scope through explicit,
consistent row `timing_scope` values. When present, metadata declarations must
agree with every row. This compatibility path uses recorded evidence; it does
not assign current semantics to an unlabelled file.

Comparison retains the loaded run rows and applies the same timing owner to
metadata, aggregate and runs before computing ratios or competitive rankings.
Ordinary admission first checks recorded declarations for consistency, before
resource grouping; this does not assign a scope to unlabelled legacy inputs.
An explicitly conflicting run scope is rejected even when all aggregate scopes
agree. Unlabelled historical reports remain readable for inspection; they do
not become comparable by omitting a scope.

For an unlabelled historical ordinary report, either retain it for inspection
without ratios or establish its actual boundaries from the producing source
revision. Any justified annotation belongs in a separate reviewed copy with
the evidence for its scope, preserving the original. There is no automatic
upgrade command or permissive comparison override.

## Isolated report merging

Every successful child report must declare a supported scope for its actual
suite/profile. All children must agree before aggregate rows or direct ratios
are combined. The parent retains that verified scope. Unknown, missing,
contradictory or mixed scopes raise an explicit error rather than inheriting
the first child's label. Failed children retain their existing diagnostics and
validity treatment; they are not promoted into successful measurements.

## Regression checks

Deterministic tests use a two-second fake workload with seven seconds of
sampler entry and twenty seconds of sampler exit. Reported load duration must
be two seconds, while entry, exit and client cleanup must still complete.
Separate tests cover warmup, CPU boundaries, exceptions, cancellation,
generated reports, compatible and incompatible comparison, and isolated
merging. These tests do not constitute a performance study.
