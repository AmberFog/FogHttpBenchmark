# FogHTTP Benchmark

Reproducible benchmark suite for [FogHTTP](https://github.com/AmberFog/foghttp)
and comparable Python HTTP clients. The benchmark installs `foghttp` from PyPI
and treats it as an external user-facing dependency.

The goal is not marketing-perfect numbers. The goal is a repeatable, readable
harness that shows real trade-offs across buffered HTTP workloads, redirects,
pool contention, delay scenarios, resource usage, and client lifecycle cost.
For FogHTTP `0.3.x`, the harness also includes a dedicated
resource/backpressure suite for active request limits, per-origin limits,
pending queues, pool timeouts, and buffered response body limits, plus a
one-upstream API client suite for `base_url`, client defaults, params merging,
prepared requests, and request body encoding. It also includes a request
builder suite for Python-side `build_request()` and query construction cost,
and a compressed-response suite for transparent `gzip`, `deflate`, and `br`
decode overhead. For FogHTTP `0.3.2+`, it includes a response-streaming suite
for full body consumption, slow body chunks, first-chunk latency, text/line
iteration, and early-close cleanup.
For FogHTTP `0.3.4+`, it includes a proxy CONNECT suite for explicit
`proxy=`, `trust_env=True`, HTTP proxy routing, HTTPS CONNECT setup/reuse, and
short-lived CONNECT client overhead.

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
uv sync
```

The project dependency on `foghttp` is resolved from PyPI:

```toml
"foghttp>=0.3.5,<0.4"
```

To benchmark a different released version, change the dependency constraint and
refresh the lock file. Avoid benchmarking a local editable checkout unless the
explicit goal is pre-release development analysis.

## Request Benchmark

```bash
uv run foghttp-benchmark \
  --clients foghttp,httpx,httpxyz,aiohttp,zapros \
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
  --clients foghttp,httpx,httpxyz,aiohttp,zapros \
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
  --clients foghttp,httpx,httpxyz,aiohttp,zapros \
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
  --clients foghttp,httpx,httpxyz,aiohttp,zapros \
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
  --clients foghttp,httpx,httpxyz,aiohttp,zapros \
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
  --clients foghttp,httpx,httpxyz,aiohttp,zapros \
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

## Proxy CONNECT Benchmark

```bash
uv run foghttp-benchmark \
  --suite proxy-connect \
  --clients foghttp,httpx,httpxyz,aiohttp,zapros \
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

## Outputs

Each run writes timestamped JSON and Markdown reports plus `latest.json` and
`latest.md` links/copies in the selected output directory. Generated results are
ignored by git by default. Publish selected reports intentionally when they are
part of a release or benchmark note.

## Subprocess Isolation

Benchmark runs are isolated by default. The public CLI always runs selected
clients and scenarios through sequential subprocesses so one benchmark group
cannot pollute the next group's loopback, proxy, TLS, environment, descriptor,
or runtime state:

```bash
uv run foghttp-benchmark \
  --suite proxy-connect \
  --clients foghttp,httpx,httpxyz,aiohttp,zapros \
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
- `warning`: usable for comparison, but noisy rows need attention.
- `needs-rerun`: benchmark numbers are diagnostic only until the run is repeated.
- `invalid`: proxy routing, child process, or report integrity checks failed.

Validity gates detect unexpected measured/warmup errors, suspicious zero
success throughput, high variation, failed isolated child processes, proxy
usage guard failures, and missing proxy counters. Resource/backpressure cases
with intentionally induced `PoolTimeout`, response body limit, or aggregate
buffered budget errors are treated as expected pressure scenarios; recovery
failures still mark the run as `needs-rerun`.

Compare reports surface input validity. If either input is `needs-rerun` or
`invalid`, competitive rankings are blocked and the comparison is diagnostic
only. Historical monolithic all-client proxy-connect runs from 2026-06-07 are
diagnostic artifacts, not performance baselines.

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

```bash
uv sync --extra dev
uv run python -m py_compile foghttp_benchmark/*.py foghttp_benchmark/clients/*.py foghttp_benchmark/creation/*.py
uv run --extra dev ruff format .
uv run --extra dev ruff check .
uv run --extra dev mypy
pre-commit run --all-files
```

Keep benchmark code decomposed. If a scenario grows into a subsystem, split it
into modules before it becomes difficult to review.
