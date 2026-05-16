# FogHTTP Benchmark

Reproducible benchmark suite for [FogHTTP](https://github.com/AmberFog/foghttp)
and comparable Python HTTP clients. The benchmark installs `foghttp` from PyPI
and treats it as an external user-facing dependency.

The goal is not marketing-perfect numbers. The goal is a repeatable, readable
harness that shows real trade-offs across buffered HTTP workloads, redirects,
pool contention, delay scenarios, resource usage, and client lifecycle cost.
For FogHTTP `0.2.x`, the harness also includes a dedicated
resource/backpressure suite for active request limits, per-origin limits,
pending queues, pool timeouts, and buffered response body limits.

## What It Measures

- async and sync buffered request throughput
- latency percentiles per scenario
- redirect behavior for GET, HEAD, and POST
- local pool contention and delayed responses
- peak RSS, thread count, and file descriptor pressure
- client creation, first request, reuse, and close cost

## Install

```bash
uv sync
```

The project dependency on `foghttp` is resolved from PyPI:

```toml
"foghttp>=0.2,<0.3"
```

To benchmark a different released version, change the dependency constraint and
refresh the lock file. Avoid benchmarking a local editable checkout unless the
explicit goal is pre-release development analysis.

## Request Benchmark

```bash
uv run foghttp-benchmark \
  --clients foghttp,httpx,aiohttp,zapros \
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
  --clients foghttp,httpx,aiohttp,zapros \
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

This suite is FogHTTP-specific because it uses `TransportStats` from the public
`0.2.x` API. It checks global active request slots, per-origin active request
slots, bounded pending requests, `PoolTimeout` behavior, recovery after timeout
bursts, and `max_response_body_size` cleanup.

## Outputs

Each run writes timestamped JSON and Markdown reports plus `latest.json` and
`latest.md` links/copies in the selected output directory. Generated results are
ignored by git by default. Publish selected reports intentionally when they are
part of a release or benchmark note.

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
- Local loopback results do not measure real internet latency, DNS behavior,
  TLS handshake cost, HTTP/2, proxies, cookies, streaming, or auth flows.

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
