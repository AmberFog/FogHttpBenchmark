# FogHTTP Benchmark

Reproducible benchmark suite for [FogHTTP](https://github.com/AmberFog/foghttp)
and comparable Python HTTP clients. The benchmark installs `foghttp` from PyPI
and treats it as an external user-facing dependency.

The goal is not marketing-perfect numbers. The goal is a repeatable, readable
harness that shows real trade-offs across buffered HTTP workloads, redirects,
pool contention, delay scenarios, resource usage, client lifecycle cost,
compressed response decoding, response streaming, and proxy CONNECT routing.
Zapros is measured in two forms when supported by a suite: `zapros` uses the
standard Zapros network handler, while `zapros-pyreqwest` uses
`zapros[pyreqwest]` and the PyReqwest-backed handler as a separate client row.

## What It Measures

- async and sync buffered request throughput
- latency percentiles per scenario
- redirect behavior for GET, HEAD, and POST
- local pool contention and delayed responses
- peak RSS, thread count, and file descriptor pressure
- client creation, first request, reuse, and close cost
- one-upstream API client overhead for defaults and prepared requests
- pure request builder overhead before network I/O
- transparent compressed response decode overhead
- bytes-first response streaming throughput and cleanup
- explicit proxy and HTTPS CONNECT overhead
- aggregate buffered response budget behavior

## Install

```bash
uv sync --locked
```

The project dependency on `foghttp` is resolved from PyPI:

```toml
"foghttp>=0.4.0,<0.5"
```

To benchmark a different released version, change the dependency constraint and
refresh the lock file. Avoid benchmarking a local editable checkout unless the
explicit goal is pre-release development analysis.

### Source-pinned streaming research

The opt-in streaming study builds an isolated release wheel from a reviewed
FogHTTP source revision. See [preparation, profiles and evidence contracts](docs/async-streaming-research.md).
The ordinary environment above continues to use the locked PyPI dependency.

### CLI configuration

Suite/profile defaults apply only to omitted options. Explicit values, including
`--requests 2000`, `--warmup 200` and the common concurrency/scenario lists, are
preserved and checked by the selected suite. Unsupported scenarios are rejected.
Programmatic `BenchmarkArgs` fields are effective values; callers must choose
suite defaults explicitly. See [defaults and programmatic migration](docs/cli-configuration.md).

## Request Benchmark

```bash
uv run foghttp-benchmark \
  --clients foghttp,httpx,httpxyz,aiohttp,zapros,zapros-pyreqwest \
  --modes async,sync \
  --requests 500 \
  --warmup 50 \
  --repeats 3 \
  --concurrency 1,10,50,100 \
  --scenarios json-small,json-decode-small,bytes-64k,post-json-echo,post-echo-64k,redirect-get-302,redirect-head-302,redirect-post-303,redirect-post-307 \
  --output-dir results/local
```

## Client Creation Benchmark

```bash
uv run foghttp-benchmark \
  --suite client-creation \
  --clients foghttp,httpx,httpxyz,aiohttp,zapros,zapros-pyreqwest \
  --modes async,sync \
  --iterations 100 \
  --repeats 3 \
  --client-counts 1,10,50 \
  --output-dir results/client-creation
```

## Resource / Backpressure Benchmark

```bash
uv run foghttp-benchmark \
  --suite resource-backpressure \
  --clients foghttp \
  --modes async,sync \
  --requests 200 \
  --warmup 0 \
  --repeats 3 \
  --concurrency 10,50,100 \
  --output-dir results/resource-backpressure
```

This suite is FogHTTP-specific because it uses FogHTTP public transport
diagnostics. It checks global active request slots, per-origin active request
slots, bounded pending requests, `PoolTimeout` behavior, recovery after timeout
bursts, `max_response_body_size` cleanup, and
`max_buffered_response_bytes` aggregate budget behavior.

## Compressed Response Benchmark

```bash
uv run foghttp-benchmark \
  --suite compressed-response \
  --clients foghttp,httpx,httpxyz,aiohttp,zapros,zapros-pyreqwest \
  --modes async,sync \
  --requests 1000 \
  --warmup 100 \
  --repeats 3 \
  --concurrency 1,10,50 \
  --output-dir results/compressed-response
```

This suite measures transparent decode overhead for buffered compressed
responses: small JSON, 64 KiB bodies, a high-ratio 1 MiB body, and a multi-field
`Content-Encoding` response. It is useful for checking the cost of FogHTTP
response decoding against clients that already perform automatic decompression.

## One-Upstream API Client Benchmark

```bash
uv run foghttp-benchmark \
  --suite one-upstream \
  --clients foghttp,httpx,httpxyz,aiohttp,zapros,zapros-pyreqwest \
  --modes async,sync \
  --requests 1000 \
  --warmup 100 \
  --repeats 3 \
  --concurrency 1,10,50 \
  --output-dir results/one-upstream
```

This suite compares `foghttp`, `httpx`, and `httpxyz` in the common
service-client pattern: one upstream per client, `base_url`, default headers,
default params, per-request params, JSON/form bodies, and prepared requests.
Clients without a semantics-compatible defaults API are reported as skipped.

## Request Builder Benchmark

```bash
uv run foghttp-benchmark \
  --suite request-builder \
  --clients foghttp,httpx,httpxyz,aiohttp,zapros,zapros-pyreqwest \
  --modes async,sync \
  --iterations 5000 \
  --warmup 500 \
  --repeats 3 \
  --output-dir results/request-builder
```

This suite measures Python-side `build_request()` cost separately from network
I/O. Pure build cases do not start a server. The `send-prepared-get` case starts
the local loopback server and measures the combined build-plus-send path through
a reused client. Unsupported clients are reported as skipped.

## Response Streaming Benchmark

```bash
uv run foghttp-benchmark \
  --suite response-streaming \
  --clients foghttp,httpx,httpxyz,aiohttp,zapros,zapros-pyreqwest \
  --modes async,sync \
  --requests 200 \
  --warmup 50 \
  --repeats 3 \
  --concurrency 1,10,50 \
  --output-dir results/response-streaming
```

This suite measures response streaming across raw bytes, decoded UTF-8 text
chunks, line iteration, and early-close scenarios. It reports stream throughput,
MiB/s, lines/s, first-item latency, resource peaks, and FogHTTP transport/body
lifecycle counters when available. FogHTTP streaming requires PyPI `0.3.2` or
newer. Local or pre-release runs should still be labeled explicitly through
report metadata and the output directory.

The opt-in `lifecycle` and `async-bytes` profiles place server and client in
separate processes and retain independent resource observations, integrity and
cleanup controls. The latter adds bounded delivery traces, continuous load
windows and explicit diagnostic profilers. See the
[streaming research guide](docs/async-streaming-research.md) for limits,
commands and interpretation. Ordinary streaming still measures a shared
client/server process and event loop.

## Proxy CONNECT Benchmark

```bash
uv run foghttp-benchmark \
  --suite proxy-connect \
  --clients foghttp,httpx,httpxyz,aiohttp,zapros,zapros-pyreqwest \
  --modes async,sync \
  --requests 100 \
  --warmup 20 \
  --repeats 3 \
  --concurrency 1,10,50 \
  --output-dir results/proxy-connect
```

This suite starts local HTTP and HTTPS loopback origins plus a deterministic
HTTP proxy with CONNECT support. It compares direct baseline, explicit
`proxy=`, and `trust_env=True` routing for clients with comparable client-level
proxy APIs. Reports include proxy request counters, CONNECT handshakes,
latency, throughput, resource peaks, and FogHTTP transport stats when
available. Clients without comparable client-level proxy support are reported
as skipped. The suite requires `openssl` on `PATH` to generate a temporary
local CA and localhost server certificate at runtime.
The CA declares its subject key identifier; the server certificate declares
both subject and authority key identifiers. Generation does not depend on
OpenSSL's implicit extension defaults. Client certificate chain and hostname
verification remain enabled.

## Outputs

New reports declare `metadata.report_schema_version: 1`. Comparison and isolated
child admission share a strict reader: required fields cannot become zero,
numeric strings and non-finite numbers are rejected, and counter totals must
agree with any recorded error maps. Saved parent/child validity restrictions
remain in force. See [saved report schemas and legacy policy](docs/report-schemas.md).

Aggregate identities must be unique within a report and across merged children.
Identical duplicates also fail admission, with both source positions reported;
raw run repetitions remain valid. See [identity and comparison groups](docs/report-schemas.md#aggregate-identity-and-comparison-groups).

Each run writes timestamped JSON and Markdown reports plus `latest.json` and
`latest.md` links/copies in the selected output directory. Generated results are
ignored by git by default. Publish selected reports intentionally when they are
part of a release or benchmark note.

Ordinary reports use resource metric schema `2`: unavailable measurements stay
JSON `null`, measured zero stays numeric, and each aggregate resource field
records available and expected repeat observations in `resource_coverage`.
Markdown distinguishes unavailable values and partial coverage. Historical
files without coverage retain unknown completeness. See
[resource measurement contracts](docs/resource-measurements.md).

## Subprocess Isolation

Benchmark runs are isolated by default. The public CLI always runs selected
clients and scenarios through sequential subprocesses so one benchmark group
cannot pollute the next group's loopback, proxy, TLS, environment, descriptor,
or runtime state:

```bash
uv run foghttp-benchmark \
  --suite proxy-connect \
  --clients foghttp,httpx,httpxyz,aiohttp,zapros,zapros-pyreqwest \
  --modes async,sync \
  --output-dir results/proxy-connect-isolated
```

The parent process runs each client/scenario pair sequentially in subprocesses,
each child writes the normal suite-specific report, and the parent writes a
merged JSON report with child exit codes, stdout/stderr tails, duration, peak
RSS, threads, and file descriptors. Suites without scenario dimensions fall
back to per-client subprocess isolation. The scheduler waits `15s` by default
between child processes so loopback sockets, proxy state, TLS state,
descriptors, runtime resources, and OS TCP state can settle before the next
measurement group starts. Override this only for explicit diagnostics with
`FOGHTTP_BENCHMARK_CHILD_COOLDOWN_S`; the actual cooldown is written to report
metadata as `metadata.isolation.child_cooldown_s`. If a child fails, the parent
still writes diagnostics and exits with an error so invalid runs are not
treated as successful measurements.

Request-style suites also apply a short per-run settle step after high TCP
connection churn. This protects full matrices from loopback ephemeral-port and
`TIME_WAIT` contamination when a client/scenario opens hundreds of short-lived
connections in one measured run. The default is `3s` after a run with at least
`256` opened connections or any connection-open failures. Override only for
explicit diagnostics with `FOGHTTP_BENCHMARK_RUN_COOLDOWN_S` and
`FOGHTTP_BENCHMARK_RUN_COOLDOWN_OPENED_THRESHOLD`; actual values are written to
request-style report metadata as `metadata.run_settling`.

## Run Validity

Reports include `metadata.validity` and a Markdown `Run Validity` section. The
status is one of `valid`, `warning`, `needs-rerun`, or `invalid`:

- `valid`: no detected report-quality issues.
- `warning`: detected noise or an expected compatibility limitation; check
  `can_compare` before using competitive rankings.
- `needs-rerun`: benchmark numbers are diagnostic only until the run is repeated.
- `invalid`: proxy routing, child process, or report integrity checks failed.

Validity gates detect unexpected measured errors, reported warmup errors,
suspicious zero success throughput, high variation, failed isolated child
processes, proxy usage guard failures, and missing proxy counters.
Request-builder reports currently omit warmup failures; their comparison
cannot certify a clean warmup. Retain that limitation when interpreting them. Resource/backpressure cases
with intentionally induced `PoolTimeout`, response body limit, or aggregate
buffered budget errors are treated as expected pressure scenarios; recovery
failures still mark the run as `needs-rerun`.

Compatibility exceptions retain their exact client, mode, scenario, and phase
scope. The known sync warmup `RuntimeError` exception does not apply to measured
errors. Measured `RuntimeError`, unknown errors, mixed expected/unexpected
errors, and fully failed rows block performance comparison.

Compare reports surface input validity and honor `can_compare`. An expected
compatibility limitation adds a `warning` reason but blocks competitive rankings
for the report until comparable and compatibility rows are separated in
TASK-034. A high-variation warning alone remains comparable. If either input is
`needs-rerun` or `invalid`, the comparison is diagnostic only. Zero success
throughput still requires a rerun, including known compatibility failures.
Loading an older report rechecks its rows and preserves any stronger recorded
failure; saved validity metadata cannot bypass the current gates. Historical
monolithic all-client proxy-connect runs from 2026-06-07 are diagnostic artifacts,
not performance baselines.

## Compare Reports

Use `compare` to turn two JSON reports from the same suite into a compact
Markdown delta report:

```bash
uv run foghttp-benchmark compare \
  results/full-requests/latest.json \
  results/full-requests-0.2.1/latest.json \
  --output results/compare-requests.md
```

The comparison highlights geomean and median ratios, competitive wins for valid
inputs, per-mode/per-scenario deltas, top improvements, top regressions, error
rows, resource peaks, and unmatched focus rows.

Comparison also requires the same supported `metadata.timing_scope`. Unknown
or incompatible timing contracts are rejected before ratios are calculated.
Older files remain readable; an absent scope is not automatically upgraded.
See [measurement timing contracts](docs/measurement-timing.md) for the scope
identifiers, isolated-report checks and legacy policy.

## Progress Output

Benchmark runs show stages and completed run counts by default. Use
`--no-progress` for quiet machine-readable runs:

```bash
uv run foghttp-benchmark --no-progress --output-dir results/local
```

Interactive terminals use Rich progress bars. Plain log output keeps outer
suite milestones, while inner request-load progress is emitted as a heartbeat
only for long-running stages.

## Methodology

- Benchmarks use a local asyncio HTTP/1.1 loopback server.
- Ordinary HTTP suites colocate server, client and harness in one child
  process; async server/client work shares its event loop. CPU and RSS describe
  that combined system. Separate-PID streaming profiles are opt-in.
- Requests (including compressed responses), one-upstream, proxy-connect and
  resource/backpressure measure load inside active samplers. Warmup, sampler
  entry/exit, recovery checks and outer client close are excluded. Work required
  by a scenario, such as creating a fresh client for each request, remains timed.
- Each report declares a versioned timing contract. Creation, request-builder
  and the different streaming profiles retain their own boundaries, described
  in [measurement timing contracts](docs/measurement-timing.md). Correcting
  timing boundaries is not evidence of a FogHTTP performance improvement.
- Scenarios are shuffled by default with a stable seed.
- Sync and async results should be compared separately.
- In request reports, `limit` means the configured benchmark pressure limit.
  For FogHTTP `0.2.x` it maps to active request slots and idle pool capacity;
  for other clients it maps to their connection pool limit.
- Higher `ok/s` or lifecycle `ops/s` is better.
- Lower latency, thread count, file descriptor count, memory delta, and errors
  are better.
- Local loopback results do not measure real internet latency, real DNS
  behavior, HTTP/2, cookies, or auth flows. Proxy and HTTPS CONNECT behavior is
  measured only through the dedicated local proxy suite.

## Development

Python 3.11 is the minimum supported version. Run the full tests on both 3.11
and 3.14 when changing version-sensitive behavior.

```bash
uv sync --locked --extra dev
uv lock --check
uv run --locked foghttp-benchmark --help
uv run --locked --extra dev python -m py_compile foghttp_benchmark/*.py foghttp_benchmark/clients/*.py foghttp_benchmark/creation/*.py
uv run --locked --extra dev pytest -q
uv run --locked --extra dev pytest -q tests/architecture
uv run --locked --extra dev ruff format --check .
uv run --locked --extra dev ruff check .
uv run --locked --extra dev mypy
uv run --locked --extra dev pre-commit run --all-files
```

Ruff, uv and mypy use their provided pre-commit hooks. The lock hook checks
consistency without updating the lock file; update dependencies explicitly
and review the resulting diff. Formatting and lint hooks retain their
automatic fixes, so review any files they modify. The isolated mypy hook checks
the whole package with strict project settings. It uses
`--python-executable=.venv/bin/python` to find dependency types in the project
environment, without a duplicate dependency list or automatic type-stub
installation. Run `uv sync --locked --extra dev` before the hooks and again
after changing `pyproject.toml` or `uv.lock`: the hook does not install or
synchronize project dependencies. A missing interpreter fails the check;
an outdated environment may expose outdated APIs.

Keep benchmark code decomposed. If a scenario grows into a subsystem, split it
into modules before it becomes difficult to review.

Follow the [architecture and extension guide](docs/architecture.md):

- A suite owns its scenarios, measurement and orchestration. Register all four
  `SuiteDefinition` callbacks and test dispatch, merge and cleanup behavior.
- A client implements its suite adapter and matching sync/async factory. Keep
  thread and close boundaries explicit; unavailable optional statistics remain
  `None`.
- A report prepares metadata, validity and display values before rendering and
  publication. Test saved-report admission, contents and failure behavior.

Every extension preserves timing scopes, nullable resource coverage, aggregate
identity, EOF/integrity and provenance/evidence checks. Import-boundary tests
protect selected dependency directions; behavioral tests remain required for
each changed contract. Research profiles retain their separate evidence and
publication paths.

Client registrations use mode-specific specifications and typed adapter
factories. See [client adapter contracts](docs/client-adapters.md) for dispatch,
optional statistics and migration of internal constructors.

See [internal streaming measurement types](docs/streaming-measurement-types.md)
for typed CPU/sample/batch records and their boundary with validated JSON reports.

See [application execution](docs/application-execution.md) for parent/child
entrypoint ownership and migration of programmatic imports from `cli.py`.

See [suite composition](docs/suite-composition.md) for the explicit suite mapping,
local orchestration ownership and the steps for adding a benchmark suite.

See [merged report semantics](docs/merged-report-semantics.md) for suite-owned
proxy ratios, streaming metadata agreement and mandatory merge validity checks.

See [statistical primitives](docs/statistical-primitives.md) for shared ordinary
CV, percentile and error counters, and the separate optional research policies.

See [report rendering](docs/report-rendering.md) for ready typed contexts,
template loading, pure Markdown rendering and migration of internal imports.

See [prepared report publication](docs/report-publication.md) for shared file
writing, preparation order, latest overwrite behavior and partial failures.
