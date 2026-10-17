# Async streaming research

This guide describes the opt-in profiles in the existing `response-streaming`
suite. It is a procedure and evidence contract, not a performance result.
Start with a bounded pilot and one named hypothesis. Keep profiler runs
separate from controls. Do not expand a noisy campaign indefinitely; missing
attribution is `insufficient_data`.

## Release-wheel preparation

The TASK-124 investigation uses only commit
`51a25f232d3ef39869f1f182596ac64d7aab11f6` from `AmberFog/foghttp`
branch `release/0.4.2`. The preparation command refuses a missing or advanced
release branch. A new baseline requires a reviewed, explicit source change.

The reviewed preset in
[`research_baseline.py`](../foghttp_benchmark/research_baseline.py) owns the
source and build pins: Rust/Cargo `1.95.0`, Maturin `1.14.1`, setuptools `80.9.0`
and wheel `0.45.1`. Native preparation supports these host/target pairs:

| Host | Native target |
| --- | --- |
| macOS arm64 | `aarch64-apple-darwin` |
| Linux aarch64 | `aarch64-unknown-linux-gnu` |

Other platforms fail explicitly. Select an existing Python interpreter with
`--python`; the manifest records its full version and ABI. Python version,
platform and toolchain changes define separate baselines. Thread-scoped
cProfile attribution requires separately qualified CPython 3.11, as described
below. Support for a target does not certify a particular machine's results.

Run from the benchmark root with a new output directory under ignored
`results/`, or outside the repository. An unignored output inside the checkout
is rejected before build work: generated artifacts must not enter its source
fingerprint. Use a fresh directory name on each preparation:

```bash
research_dir="$(pwd)/results/async-streaming-0.4.2/prepare-001"
env -u RUST_LOG .venv/bin/python -m foghttp_benchmark.research prepare \
  --python "$(pwd)/.venv/bin/python" \
  --output-dir "$research_dir"
```

Preparation preserves the ordinary development environment. It clones a fresh
detached FogHTTP checkout, isolates Cargo home and target directories, and uses
`maturin build --release --locked --target <native-target> -vv`.
Unrecorded compiler, Cargo profile, Python and dynamic-loader overrides fail
before preparation. The retained build log must show the native crate compiled
with `opt-level=3` and Cargo's optimized release completion.

A fresh research venv receives hash-checked dependencies exported from the
benchmark lock with FogHTTP excluded, then the exact local FogHTTP wheel and
a regular benchmark wheel. The benchmark wheel comes from a recorded snapshot
of the current checkout, including existing changes; the manifest contains
the full benchmark commit, branch, dirty diff hash and file hashes. This avoids
committing unrelated work just to obtain a clean source identifier.

The output contains `manifest.json`, both wheels, full source snapshots,
dependency files, tool versions, command logs and `checksums.sha256` covering
the retained manifest, requirement files, wheels and logs. Verification checks the wheel
and installed RECORD, Python package files, native bytes, installation metadata,
interpreter and harness identity. Preparation also runs one digest-checked local
HTTP/1.1 streaming smoke without collecting performance measurements.

Repeat the isolated verification directly, outside both source checkouts:

```bash
cd /tmp
"$research_dir/venv/bin/python" -I -m foghttp_benchmark.research verify \
  --manifest "$research_dir/manifest.json" --check-remote
```

Use that venv's interpreter directly for later authorized research runs.
Ordinary `uv run` or `uv sync` can restore the PyPI FogHTTP dependency and
invalidate this baseline. Set `FOGHTTP_BENCHMARK_RESEARCH_MANIFEST` to the
absolute manifest path when running the benchmark; parent and child reports
retain the verified manifest and fingerprint, and any mismatch stops the run.

## Isolated Streaming Lifecycle Profile

The existing `response-streaming` suite has an explicit lifecycle profile.
The ordinary suite and its scenario matrix keep their defaults. This command
is for a later authorized manual run; implementation checks do not run this
baseline campaign:

```bash
.venv/bin/foghttp-benchmark \
  --suite response-streaming \
  --streaming-profile lifecycle \
  --output-dir results/streaming-lifecycle-manual \
  --no-progress
```

Use a new output directory for every launch. The profile selects FogHTTP and
HTTPX, sync and async, concurrency 1/10, and three fresh repetitions of both
`first-chunk-close-1m` and `stream-1m` (48 sequential cases). Each case creates
a server process and a client process, with the launcher sampling their PIDs
from outside the client event loop. One client is reused for two warmup rounds
and five batches of 20 rounds; a round starts C streams. Explicit `--clients`,
`--modes`, `--concurrency`, `--scenarios`, and `--repeats` select a smaller matrix.
For this profile, `--warmup` means warmup rounds, `--requests` means rounds per
batch, and `--iterations` means batches. Larger workloads are rejected.

Both cases receive the same uncompressed 1 MiB HTTP/1.1 body, with Content-Length,
identity encoding, connection close, and 64 KiB server writes. Public iterator
chunks are determined by the client; actual first-chunk sizes, delivered bytes,
framing and EOF are retained. EOF requires full length and SHA-256 integrity;
early-close bytes must match the deterministic body prefix.
Per-stream duration includes context entry, public iteration, incremental
SHA-256 and context exit. Close-return duration measures context exit itself.
Round throughput includes scheduling and scalar collection, while client
construction, client close, settling and phase probes have separate observations.

Untimed controls hold the server's tail until every client context has exited,
then release it explicitly. Only these verified unread-body exits count as
expected aborts. Each control must settle and complete an EOF recovery round.
Async controls additionally cancel and await owned workers during body wait
and while consumption is paused after the first public bytes. If cancellation
does not settle, the client is not closed underneath live workers: the parent
reaps its process and marks the case failed. Sync cancellation is explicitly
unsupported. Unknown exceptions and timeouts remain failures. FogHTTP quiet
state accounts for idle connections inside `active_connections`; live counters
are preserved before client close, with unavailable observations labelled after it.

The parent enforces a 240-second case deadline, five-second settlement budget,
2 GiB current RSS ceiling for each owned PID, and bounded scalar samples. Missing
RSS prevents enforcement and fails the guard. Resource observations contain
current RSS in bytes, sampled peaks, fd/thread counts, user/system CPU phase
deltas, actual intervals, probe durations, and nulls with reasons for unavailable
metrics. Lifetime high-water RSS is separate from current and sampled RSS.
Short peaks can be missed; stable RSS does not prove memory bounds or no leaks.
Before-load, warmup, settled batches, before/after close and post-GC phases are
retained. GC policy and request settings are recorded.

JSON and Markdown retain per-case PIDs, complete worker reports, errors and
resource series. The plan, seed, package versions, harness identity and research
provenance are preserved. Partial plans, failed controls, PID/provenance mismatch
or truncated samples invalidate a run. Spread above 10% across at least three
fresh repetitions is flagged; investigate at most one named diagnostic wave,
then classify persistent noise or missing attribution as inconclusive.
Early-close and EOF byte throughput do not represent equal work and receive
no competitive ranking. Old JSON remains readable; shared-process RSS/fd/thread
metrics are explicitly incomparable with this profile's separate PID scope.

Small correctness checks can be run without the research campaign:

```bash
.venv/bin/python -m pytest tests/streaming/test_lifecycle_process_integration.py
```

The TASK-039 artifact remains an immutable installation record of its harness
snapshot. Later source changes intentionally fail its fingerprint check.
Before authorized FogHTTP 0.4.2 research, prepare and verify a fresh harness
snapshot using the release-wheel workflow above; do not reuse the old manifest
with changed code or let environment synchronization restore the PyPI wheel.

## Controlled Async Bytes Attribution Profile

`--streaming-profile async-bytes` extends the same `response-streaming` suite
and the lifecycle process boundary above. It supports FogHTTP/HTTPX, async,
`stream-1m`, concurrency 1/10 and at most three fresh repetitions. The scenario
name is retained; the actual payload size is always recorded independently.
Defaults are 1 MiB payload, 64 KiB server writes, native client reads, no delays,
two warmup rounds, five batches of 20 rounds and three repetitions. Ordinary
suite defaults are unchanged. Early close, body-wait cancellation, paused
consumer cancellation, settlement and verified EOF recovery remain separate
mandatory lifecycle controls, outside the throughput interval.

For an explicitly bounded continuous load window, set
`--streaming-minimum-duration-s 1 --streaming-max-window-streams 2048 --iterations 1`.
The default zero duration keeps the existing fixed-round contract. A window
accepts targets from 1 to 5 seconds, retains `--requests` (at most 20) as the
minimum rounds, and stops after a whole round at the duration or hard stream
cap. Missing the duration yields `needs-rerun`; it never counts partial reads
as a speedup. Warmup remains fixed. Every stream retains its own EOF, framing,
byte count and SHA-256; only its detailed histogram moves to one exact shared
window table of at most 1024 unique sizes. Detailed records remain capped at
4096 across the entire window. Finalization and replay follow the single
wall/CPU interval. Exact replay uses at most 64 segments, each within the
existing 256 MiB/one-million-chunk limits, with complete histogram coverage.
Receipt/sidecar, RSS and timeout limits are unchanged. The new evidence uses
schema 3 / policy `async-bytes-v2`; it is not directly comparable to old scopes.

`--streaming-server-observations` optionally records bounded body write/drain
timings and transport queue observations; it is off by default. The additional
clock reads/coroutine work can affect throughput, so pair these cells with
observer-off controls. `/summary` supplies compact health counters without an
ever-growing list of earlier streams. Body loop wall sums overlap under
concurrency; `drain` completion is not proof of client receipt or spare server
capacity. A same-server HTTPX control can probe attainable load, but differences
in client chunking/buffering do not identify the Rust/Python bridge cost.

The research CLI requires a freshly verified
`FOGHTTP_BENCHMARK_RESEARCH_MANIFEST` and checks the release branch before launch.
Changing harness source intentionally invalidates an older snapshot. Prepare a
new installed harness wheel/snapshot using the release-wheel workflow; retain
the selected FogHTTP native wheel and its original build evidence. Proxy
environment variables, including `NO_PROXY` and lowercase variants, must be
absent; their presence is recorded without values. Both factories disable
`trust_env`. The server is local HTTP/1.1 with Content-Length, connection close,
no Transfer-Encoding or Content-Encoding, and a deterministic nonconstant bytes
payload. It does no text, line or JSON processing in the measured response path.

Parameters belong only to this opt-in profile; using them with another profile
fails rather than silently ignoring them:

| Parameter | Meaning and bound |
| --- | --- |
| `--streaming-payload-bytes` | Expected full response bytes, at most 1 MiB. |
| `--streaming-server-write-bytes` | Server write fragment, positive and smaller than the payload. |
| `--streaming-server-delay-s` | Delay between server writes, 0..0.1 seconds. |
| `--streaming-read-bytes` | Optional HTTPX public iterator size, at most 1 MiB. Omit for native reads; FogHTTP requires omission. |
| `--streaming-consumer-delay-s` | Harness delay between expected body deliveries, 0..1 seconds. |
| `--streaming-instrumentation` | `control` or `diagnostic`; the latter adds bounded await/consumer timestamps. |
| `--streaming-profiler-label` | Explicit external profiler declaration; diagnostic mode required. This does not attach a profiler. |
| `--streaming-profiler` | `none` (default), `cprofile`, `sample-client/server` or Linux `perf-client/server`; an active backend requires diagnostic mode and a label. |
| `--streaming-perf-sample-frequency-hz` | `499` (default) or opt-in `1999`; nondefault frequency requires an active Linux perf backend. |
| `--streaming-chunk-sample-cap` | First-N public delivery records per stream, 1..128, subject to a shared batch budget. |

Server writes are not TCP packets, Hyper frames or public Python chunks. FogHTTP
uses its native `aiter_bytes()` without hidden rechunking. HTTPX's explicit read
size uses its own public iterator and is a different comparison condition.
A later authorized small manual series could use the following command; it is
not run by implementation checks:

```bash
FOGHTTP_BENCHMARK_RESEARCH_MANIFEST=/absolute/path/to/fresh/manifest.json \
  /absolute/path/to/isolated/venv/bin/foghttp-benchmark \
  --suite response-streaming --streaming-profile async-bytes \
  --clients foghttp,httpx --concurrency 1 --requests 1 --warmup 1 \
  --iterations 1 --repeats 3 --streaming-server-write-bytes 1024 \
  --output-dir results/async-bytes-manual --no-progress
```

Each stream incrementally hashes bytes without retaining the body. Status,
HTTP framing, EOF, exact length and SHA-256 must all pass. Failed observations
and their partial bytes/chunks remain raw evidence; only verified EOF bytes
enter primary throughput. The load timer ends immediately after the last
stream context has exited, before CPU end probes, digest finalization/verdict,
offline replay, sampler teardown, client close or disk/report I/O. Integrity is
finalized afterward: a timing endpoint never implies success by itself.
Scheduling, header observation, incremental SHA-256, scalar bookkeeping, context
exit and any configured consumer delay are included in load wall time.

Client and server CPU user/system counters are read separately around that
interval. Probe timestamps and their boundary overhang are retained: these are
bracketing process counters, not an exact decomposition of transport or Rust
work. CPU/verified-byte uses only verified bytes. CPU/wall sums all process
threads and may exceed one with multicore work. Missing counters stay null with
reasons; OS counter resolution is not inferred from nanosecond timestamp units.
Parent resource-phase CPU includes barriers and settlement and remains a
separate, broader metric. Current RSS, sampled peaks and lifetime high-water RSS
retain their separate scopes and limitations from TASK-037.

Per-stream full/first-delivery/close latency, complete chunk counts and bounded
size histograms are retained. Gaps use adjacent public delivery timestamps,
including prior hashing, bookkeeping and consumer delay. First-N samples are
biased toward stream starts; sample/dropped counts and global budget exhaustion
are explicit. Each batch permits at most 4096 combined delivery/trace records
and 4096 histogram bins across its streams. A missing histogram tail cannot be
used as a complete distribution. No payload bytes are kept in raw traces.

After load, scalar-only, SHA-only and combined in-memory replays use the exact
observed size histogram (sorted sizes, original stream order omitted), bounded
by 256 MiB and one million updates per batch. They estimate harness cost with
different cache/allocator/scheduling conditions; they exclude async scheduling,
consumer sleeps and detailed diagnostic trace. They are never subtracted from
primary throughput or presented as measured native savings. Native copy counts,
event-loop wakeups and Future completion costs remain null with an explicit
attribution limit. Detailed await traces and externally attached profilers are
diagnostic; profiler controls must target the owned client/server PID separately.

Explicit profiling uses separate launches with the same workload and an
unprofiled control. `cprofile` is enabled only during each measured load;
warmup, digest finalization, replay and profile-file writes are outside its
boundaries. On CPython 3.11 it profiles the enabling Python thread. CPython
3.12+ uses interpreter-wide monitoring: callbacks from other threads can mix
caller contexts, so those profiles are explicitly unqualified for timing/caller
attribution. The recorded thread ID identifies the enabling thread only. Use
a separately qualified CPython 3.11 environment for thread-scoped profiles;
results from different Python versions are separate baselines. The retained
`.pstats` file is tied to the recorded Python version. Its default timer measures
real time, including waits, and cannot attribute whole-process CPU or Rust
worker costs. Native code outside Python callbacks is never fully covered.

On macOS, `sample-client` and `sample-server` invoke `/usr/bin/sample` for one
second at a one-millisecond interval against the selected owned process. They
require one load window of at least two seconds. The parent starts sampling
after the first batch barrier and retains PID, command, exit, hash and timing
evidence separately from client/server resource counters. Only captures fully
inside the actual load interval qualify as load profiles. Sampling all threads
counts stack residence, including idle waits; percentages are not CPU shares.
Optimized native frames may be absent or inlined. Use symbolized caller paths
and the exact source revision to support observations; these profiles alone
cannot supply exact copy, wakeup or Future-completion costs. Profile files are
rehash-checked when loading reports; failed attachment never becomes an
unprofiled success. Diagnostic runs remain excluded from control rankings.

Linux `perf-client` and `perf-server` record the selected owned process, including
its threads, with `cpu-clock:u`, 499 Hz by default, a DWARF user-stack dump of 8192 bytes and
the monotonic clock. The half-second capture starts 0.1 seconds after the load
barrier and requires one load window of at least one second. The existing stream,
memory and timeout caps remain hard. The executable path, version and hash, raw
`perf.data`, event attributes and extracted stacks are retained. Qualification
requires the owned PID, actual sample timestamps inside load, matching user-mode
event/clock attributes and no lost/throttled records. Missing tools or permission
failures never become unprofiled success. Native sample backends retain their
two-second minimum and their distinct wall-stack scope.

An explicit `--streaming-perf-sample-frequency-hz 1999` requests denser sampling
with `--strict-freq`; unsupported kernel limits fail instead of silently lowering
the request. The declared configuration, recording argv, receipt and event header
must agree. Older receipts without this option retain their exact 499 Hz contract.
The half-second duration, attach delay, stack and artifact bounds stay fixed.
Actual sample counts and periods depend on CPU activity and clock resolution;
1999 Hz does not guarantee four times the samples or exact user CPU duration.
Compare its profiler interference against fresh 499 Hz and unprofiled controls.

`perf` user-mode on-CPU samples exclude kernel CPU, which remains in separate
process counters. Stack proportions and sample periods are not exact operation
times, copied bytes or wakeup counts; preserve unresolved frames and unwind
limitations. A Linux VM requires its own optimized source wheel and environment
baseline. Do not pool its results with macOS. Server capacity and profiler
interference controls must use the same platform and workload conditions.

JSON retains `metadata/aggregate/runs`; hashed, bounded raw sidecars hold each
repeat's stream/chunk/resource evidence. Loading an attribution report rechecks
sidecar hashes and rebuilds summaries instead of trusting a stored PASS.
Schema/policy versions and condition fingerprints cover payload, framing,
server/read/consumer settings, timing, sampling, instrumentation, resource scope
and environment. A different source SHA requires the explicit comparison axis
`compare ... --comparison-axis foghttp-source`; other conditions and the harness source fingerprint must still
match. Old JSON remains readable; changed metric scopes are incomparable.
Diagnostic/profiler runs cannot enter control rankings.

Strong validity requires the complete declared batches/streams and controls,
integrity, release-wheel provenance, healthy server, both CPU observations in
every batch, complete overhead evidence, three fresh repetitions and at most
10% throughput variation. Missing evidence cannot become PASS through a median.
Small correctness fixtures deliberately do not qualify as research baselines:

```bash
.venv/bin/python -m pytest tests/streaming/test_attribution_process_integration.py
```

Ordinary full-bytes scenarios also use incremental integrity checks. Their
`verified-eof-v2` throughput excludes failed/incomplete/early-close bodies;
observed totals remain separate. `load-only-v2` wall time excludes sampler exit.
Their legacy adapter interface cannot retain partial observations when an
adapter raises before returning an outcome; the isolated bytes profile retains
those partial deliveries explicitly.

Clock and counter contracts follow the supported Python
[time API](https://docs.python.org/3.11/library/time.html#time.perf_counter_ns),
[psutil process counters](https://psutil.io/api/#psutil.Process.cpu_times)
and [HTTPX response API](https://www.python-httpx.org/api/#response).

## Repository and artifact boundary

Keep maintained code, regression tests, report templates, lock files and this
guide in Git. Keep generated `results/`, wheels, venvs, native source copies,
raw reports, profiles and command logs in the local artifact archive. Preserve
checksums and the complete original directories when archiving or sharing them.
A clean clone does not contain that evidence and cannot reconstruct a measured
result from this guide alone.

The 0.4.2 investigation retained `insufficient_data` for TASK-124. No substantial
removable streaming bottleneck or isolated payload allocation cost was
established. Ordinary competitor matrices measure the colocated client/server
system. They do not establish a client-only winner. See the preserved local
`results/async-streaming-0.4.2/task041-full-20261016/developer-report.md` and
`task041-whole-process-20261017/report.md` for the historical conclusions and
raw-evidence references. Changing this harness requires a fresh fingerprint
before future measurements; it does not rewrite those historical artifacts.
