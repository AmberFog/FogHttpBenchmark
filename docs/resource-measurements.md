# Resource measurement contracts

Ordinary report metadata declares `resource_metric_schema_version: 2`.
This schema preserves existing metric names and units while allowing missing
values and recording the completeness of each aggregate resource field.
The timing contracts and validity policies remain separate.

## Nullable values and coverage

Each aggregate resource value is the maximum of its available run observations.
If all observations are missing, the value is JSON `null`. A measured zero is
an observation and participates in aggregation. Boolean, nonnumeric and
nonfinite resource inputs are rejected rather than converted to zero or missing.
Signed creation deltas remain signed; negative observations are not clipped.

`resource_coverage` maps aggregate field names to:

- `available`: number of numeric observations used for that field;
- `expected`: number of supplied run records for that aggregate group;
- `unavailable_reasons`: recorded reasons, or `reason-not-recorded` when the
  producing ordinary run did not record a reason for its missing observation.

These are repeat observation counts. They are not OS sample counts, configured
repeat targets, or proof that every scheduled run succeeded. Failed children
and absent run records remain subject to existing diagnostics and validity
checks. No missing run record is silently created to manufacture coverage.

Saved-report admission checks each declared ordinary `expected` against the
aggregate's recorded `repeats`, which counts supplied records rather than the
requested repeat target in `metadata.args`. When runs are present, the reader
also checks their canonical groups and the number of non-null known resource
observations, including optional client counters. A conflicting field is
rejected before comparison or parent publication. These are count checks;
they do not recompute resource maxima or prove the integrity of ordinary raw
measurements. Aggregate-only historical inputs without coverage remain unknown.

For example, this aggregate fragment distinguishes missing, zero and partial:

```json
{
  "rss_mb_max": null,
  "threads_max": 0,
  "fds_max": 7,
  "resource_coverage": {
    "rss_mb_max": {
      "available": 0,
      "expected": 3,
      "unavailable_reasons": ["reason-not-recorded"]
    },
    "threads_max": {
      "available": 3,
      "expected": 3,
      "unavailable_reasons": []
    },
    "fds_max": {
      "available": 2,
      "expected": 3,
      "unavailable_reasons": ["reason-not-recorded"]
    }
  }
}
```

A partial maximum only summarizes available repeats. It is not equivalent to
a maximum observed across a complete series. Missing reasons cannot be
reconstructed from a numeric aggregate or its operating system.

## Fields and ownership

| Suite | Resource fields | Units and meaning |
| --- | --- | --- |
| requests, compressed-response, one-upstream, request-builder, ordinary response-streaming, proxy-connect | `rss_mb_max`, `threads_max`, `fds_max` | Existing process RSS in MiB, thread count and descriptor count. |
| client-creation | `peak_rss_delta_mb_max`, `end_rss_delta_mb_max`, corresponding `peak/end_threads_delta_max` and `peak/end_fds_delta_max` | Existing creation-operation deltas in MiB or counts; signed values are preserved. |
| resource-backpressure | Process peaks, active/pending/buffered peaks and existing final transport counters | Process RSS in MiB, transport buffer sizes in bytes, remaining fields in counts. |
| ordinary response-streaming, proxy-connect | Existing optional final client/connection counters | Counts with the same nullable and coverage rules. |

Ordinary HTTP suites retain their combined server/client/harness process scope.
This change does not alter OS probes, sampling intervals or the existing RSS
fallback. It does not turn a lifetime high-water observation into a sampled
peak, isolate client memory, or prove memory bounds. Probe entry/exit and wall
timing are governed by [measurement timing contracts](measurement-timing.md).

Separate-PID lifecycle and async-bytes profiles retain their existing per-role
sampled peaks, current-phase observations, lifetime high-water values and
unavailability reasons. They do not acquire guessed ordinary repeat coverage.

## Writers, isolation and comparison

All eight ordinary suites preserve nullable values in raw run rows and
aggregate JSON. Markdown displays missing resource values as `unavailable`,
then lists observation counts and reasons separately.

Isolation copies aggregate values and coverage without filling gaps. When all
successful children declare resource schema `2`, the parent retains that
version. Legacy or mixed children do not receive an inferred version; each
child's explicit version and each row's recorded coverage remain available.

Comparison retains resource maxima and the coverage of every matched focus
row, independently of the top-improvement display limit. It preserves recorded
lifecycle client reasons separately from server observations. Unknown resources
remain unavailable and do not receive a numeric advantage. Resource values do
not enter the throughput ranking. Available partial values remain visible with
their coverage; matching process scope alone does not establish full coverage.

## Historical reports

Files without `resource_coverage` have unknown completeness. Historical numeric
zero remains numeric zero as recorded: it could have been a real observation
or an old substituted default. There is no reliable automatic inverse mapping.
No migration guesses `null`, invents counts or rewrites preserved evidence.

Schema `2` is additive apart from making affected resource scalars nullable.
Consumers must handle `null` and inspect coverage before drawing resource
conclusions. Existing timing, provenance, error and raw-evidence gates remain
mandatory. This correction is not a new performance or memory baseline.
