# Saved report admission

New writers declare `metadata.report_schema_version: 1`. The JSON envelope has
three required fields: an object `metadata`, and object lists `aggregate` and
`runs`. Empty lists are allowed for skipped or failed execution diagnostics;
they contain no performance evidence. Unknown `report_schema_version` values and suites
are rejected. Errors include the source path and offending field path.

The same reader admits comparison inputs and successful isolated child reports.
It performs structural decoding, the legacy transformations below, numeric and
counter validation, then the existing evidence and validity checks. A corrupt
child raises before parent JSON or Markdown publication. Child source files and
process diagnostics are retained. A child must match the parent's requested suite.

## Ordinary layouts

Every aggregate row requires nonempty `mode` and `client`, the identity below,
`repeats` and `errors_total`. Each run requires the same identity, `repeat`,
`duration_s`, `errors` and its primary measurement. Modes are `async` or `sync`.
Case and scenario names remain suite-owned strings.

| Suite | Additional identity | Aggregate primary | Run primary |
| --- | --- | --- | --- |
| `requests` | `scenario`, `concurrency`, `request_limit` | `ok_req_s_median` | `ok_requests_per_second` |
| `compressed-response` | same request layout | `ok_req_s_median` | `ok_requests_per_second` |
| `client-creation` | `scenario`, `client_count`, `iterations` | `ops_s_median` | `operations_per_second` |
| `resource-backpressure` | `scenario`, `concurrency`, `request_limit`, nullable `per_origin_request_limit`, `max_pending_requests`, nullable `max_buffered_response_bytes` | `ok_requests_total` | `ok_requests` |
| `one-upstream` | `case`, `group`, `profile`, `concurrency`, `request_limit` | `ok_req_s_median` | `ok_requests_per_second` |
| `request-builder` | `case`, `group`, `kind`, `profile`, `iterations` | `ops_s_median` | `operations_per_second` |
| `response-streaming` | `case`, `read`, `consume`, `concurrency`, `request_limit` | `ok_streams_s_median` | `ok_streams_per_second` |
| `proxy-connect` | `case`, `group`, `target_scheme`, `config`, `lifecycle`, `concurrency`, `request_limit` | `ok_req_s_median` | `ok_requests_per_second` |

Request-based rows also require `requests` and measured/warmup error counters:
`warmup_errors_total` in aggregates, `warmup_errors` in runs. Runs require
`ok_requests`, or `ok_streams` for streaming. Aggregate success counts are
required where the writer records them: resource, one-upstream, proxy and streaming.
Creation and request-builder use `iterations` as the operation count.

Counts must be JSON integers, excluding booleans. Negative and fractional counts
and numeric strings are rejected. Requests, repeats, concurrency, client counts
and iterations are positive; `repeat`, pressure limits and errors can be zero.
Exit codes are signed integers. Known primary, latency and variation measurements
are finite and nonnegative; optional fields are checked when present. JSON
`NaN`, `Infinity` and `-Infinity` are rejected anywhere in the document.

Request and request-builder errors cannot exceed their operation count.
Aggregate `requests` denotes requests per repetition, so its bound is
`requests * repeats`. Client-creation counts error events: request/validation,
snapshot and cleanup can each fail in one operation. Its per-run limits follow
the existing scenario control flow (`I` is iterations, `C` is client count):

| Creation scenario | Maximum error events per run |
| --- | ---: |
| `create-close` | `I` |
| `create-first-request` | `3 * I` |
| `reused-request` | `I + 2` |
| `many-clients-open-close` | `C + 1` |
| Other historical scenario names | `I` |

Aggregate creation bounds multiply the per-run limit by recorded repeats.
For `many-clients-open-close`, recorded iterations must equal client count.
Events retain their original counts and types; accepting a diagnostic report
does not make its errors eligible for performance comparison.
Where success counts are recorded, successes plus errors must equal the
operation count. If an
`error_types` or `warmup_error_types` map is present, its values must be
nonnegative integers summing to the matching error total. Some writers and legacy
layouts lack particular maps; absence does not fabricate error classifications.
These are local row consistency checks, not ordinary-run recomputation or proof
of raw measurement integrity.

Zero throughput and expected resource-pressure failures remain representable.
Existing validity and compatibility policies decide whether they are comparable;
structural admission never grants a compatibility exception.

Resource schema `2` retains null measurements and coverage. Coverage counts and
values must agree; absence of an observation is never converted to zero.
Every recorded ordinary coverage `expected` equals the aggregate's supplied
`repeats`. If run records are present, their canonical identity groups must
agree with that count, and known resource fields' `available` counts must agree
with non-null observations. Aggregate-only inputs retain their recorded
coverage without inventing missing raw observations. These checks do not
recompute throughput or resource maxima.
Absolute resources are nonnegative. Creation deltas can be negative.
See [resource contracts](resource-measurements.md). Timing contracts and comparison
gates from [measurement timing](measurement-timing.md) remain unchanged.

## Supported legacy

Legacy means no `metadata.report_schema_version`. It uses the same required
envelope, measurements and counts, with only these explicit transformations:

- Missing suite can be inferred only when every aggregate row has one matching
  historical signature and all rows agree. Empty, unknown or mixed signatures
  fail. Historical request-shaped rows map to `requests`; compressed-response
  requires its explicit suite because its row layout is identical.
- `max_connections` supplies a missing `request_limit`. If both are present,
  they must agree and satisfy the integer contract.
- Ordinary streaming without `read` uses `bytes`.
- Absent resource metadata/coverage stays unknown. Absent timing scope remains
  readable for inspection and still blocks comparison under the timing contract.
- Absent saved validity is reclassified. A partial saved validity object may omit
  flags and reason counts, but requires a known `status` and a `reasons` list.
  Present flags, counts and reason fields are strictly validated.

Version `1` requires explicit suite and identity fields; it never repairs them
using legacy aliases. Unknown additive fields do not supply required fields;
conflicting known layouts are rejected. Old malformed reports now fail admission.
The reader does not edit historical files or infer missing measurements.

## Aggregate identity and comparison groups

The identity is the complete producer grouping key: `mode`, `client` and the
additional workload dimensions listed above. Repeats, measured values, errors
and sampled resources are not identity components. Resource budget null
is distinct from a measured/configured numeric zero. Both nullable resource limits
must be explicit, including in legacy reports; a missing key is rejected.
One-upstream and builder profiles, resource budget and proxy group are retained
when matching rows.

Streaming adds row timing and throughput distinctions. Lifecycle includes the
complete configuration as sorted-key JSON; object key order does not create a
new measurement. Async-bytes includes its condition fingerprint and primary
metric. Existing legacy scope distinctions and report timing compatibility
checks remain in force; uniqueness never qualifies a mismatched research row.

The competitor group removes only `client` from the identity. Thus FogHTTP and
HTTPX can share a group, while different profiles or pressure limits remain
separate workloads. Repeating a scenario in `runs` is a legal measurement
repetition; repeating its completed aggregate identity is a corrupt report.

Admission checks every aggregate row before metric/client filtering and before
async-bytes raw recomputation. Both identical duplicates and conflicting values
raise `Duplicate aggregate identity`, with the identity and both source indices.
Across children, diagnostics include both report paths. Checks precede parent
normalization and publication, so an existing output remains untouched on
failure. There is no first/last selection, deduplication or averaging repair.
Prepared comparison models are checked too.

For unique inputs, comparison processes rows in canonical identity order. This
stabilizes ties, summaries and resource output under permutations; the ranking
and ratio formulas are unchanged. Derived identity tuples now retain the
producer dimensions that the old comparison key omitted. The saved JSON layout
and schema version are unchanged; old files are reinterpreted through the shared
key, without rewriting them or manufacturing missing observations.

## Research and recorded restrictions

The `lifecycle` and `async-bytes` profiles use their separate research layouts.
Unavailable primary measurements in failed diagnostic rows remain null.
Metadata-level `profile` is reserved for response-streaming. Unknown or conflicting
research profile markers retain the existing invalid verdict and ranking block.
Async-bytes disk checksums and recomputation still run before validity is used;
stored success flags cannot substitute for raw evidence.

Current, saved and recorded child validity are combined conservatively: maximum
status severity, logical AND of permission flags, and deduplicated reasons.
`invalid`, `needs-rerun` and `can_compare: false` cannot become a comparison
permission when reloading or merging. Malformed validity is an error, never an
absent verdict. Structural validity alone does not establish measurement quality
or qualify a performance conclusion.
