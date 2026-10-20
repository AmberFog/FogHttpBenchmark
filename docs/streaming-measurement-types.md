# Internal streaming measurement records

`streaming/attribution_payloads.py` defines `TypedDict` contracts for data
created inside the async streaming measurement path. They remain ordinary
dictionaries at runtime.

| Producer | Internal result |
| --- | --- |
| `_cpu_snapshot` | `CpuSnapshot` |
| `_cpu_delta` | `CpuDelta` |
| `ObservationBudget.payload` | `ObservationBudgetPayload` |
| `ChunkObservations.payload` | `ChunkObservationPayload` |
| `PendingStream.finalize` | `FinalizedStreamSample` |
| `measure_async_batch` | `AttributionBatch` |

Samples retain typed delivery records, diagnostic timestamps, histogram bins,
errors and nullable header/latency fields. Batches retain typed samples,
stream errors, client/server CPU deltas and load timing. Mypy checks required
keys and numeric field types at these producers and their direct consumers.

## Missing and unavailable values

Required fields with unavailable values remain present with `None`. This
includes CPU counters and normalizations, first-delivery/close latency, absent
response headers and a sample's optional error value. A real zero remains zero.
`NotRequired` describes keys that are actually conditional: a distribution's
global scope, batch-added budget totals, and optional window/profile/server
sections. It does not make mandatory nullable observations optional keys.

A CPU snapshot is built before its end probe is recorded. Its local
`CpuSnapshotInProgress` type allows the pending end timestamp; the function
assigns that timestamp unconditionally before returning `CpuSnapshot`. The
completion cast preserves the existing probe calls and dictionary identity.
Four numeric casts in CPU delta calculation retain the existing invariant
that a successful probe supplies both counters. New runtime assertions or
substitute zero counters are not added to enforce that correlation.

## Report boundary

`_attribution_batch` keeps the concrete batch type while attaching server
metadata and handling measurement errors. `_async_batch` then erases the type
once, into the existing mixed lifecycle report's `JsonObject` representation.
This cast retains the same dictionary and creates no serialization or copy.

Replay, window, profiler and server sections keep their existing JSON
contracts outside the selected internal record shapes. The mixed lifecycle
health checks and reporting paths continue to handle JSON through their
existing checks. No loaded report or sidecar is cast to an internal
`TypedDict` as evidence of validity.

External schema admission, raw-sidecar recomputation, provenance, EOF, length,
SHA-256, framing, server health and saved/current validity checks remain
independent of these annotations. CLI options, JSON keys, units, schema
versions and historical artifacts are unchanged.

## Measurement and verification

The consume loop changes only collection annotations. Load boundaries, CPU
probe order, incremental hashing, bounds, error/cancellation behavior and
resource cleanup retain their previous behavior. CPU end probes, digest
finalization/comparison, replay and profile writing stay after the measured
load interval. No runtime schema validation, record wrappers, extra traversal
or serialization is added inside that interval.

`tests/streaming_payloads` checks positive/negative static examples, complete
JSON equality against synthetic fixtures from the prior implementation, and
CPU unavailable/decreasing/zero-normalization behavior. Existing attribution
consume, timing, window, profiling and external tamper tests remain in place.
These are correctness checks, not a new performance baseline.
