# Client modes and adapter factories

Each client family has separate frozen sync and async specifications. The
constructor fixes the mode and accepts only a factory returning the matching
adapter. The combined specification is a union for selection and planning.

| Family | Async constructor | Sync constructor | Combined type |
| --- | --- | --- | --- |
| Requests, creation, resources, compression | `AsyncClientSpec` | `SyncClientSpec` | `ClientSpec` |
| Streaming | `AsyncStreamingClientSpec` | `SyncStreamingClientSpec` | `StreamingClientSpec` |
| Request builder | `AsyncRequestBuilderClientSpec` | `SyncRequestBuilderClientSpec` | `RequestBuilderClientSpec` |
| One upstream | `AsyncOneUpstreamClientSpec` | `SyncOneUpstreamClientSpec` | `OneUpstreamClientSpec` |
| Proxy CONNECT | `AsyncProxyConnectClientSpec` | `SyncProxyConnectClientSpec` | `ProxyConnectClientSpec` |

For example:

```python
from foghttp_benchmark.streaming.factories import make_httpx_async, make_httpx_sync
from foghttp_benchmark.streaming.models import AsyncStreamingClientSpec, SyncStreamingClientSpec

async_spec = AsyncStreamingClientSpec(name="httpx", factory=make_httpx_async)
sync_spec = SyncStreamingClientSpec(name="httpx", factory=make_httpx_sync)
```

Do not pass `mode` to a specification constructor. Mypy rejects a sync factory
in an async specification and the reverse combination. Registries derive their
lookup keys from the typed specifications, preserving the requested client and
mode order, import checks and skip reasons.

## Adapter contract and dispatch

Project adapters expose a fixed `mode` with type `Literal["async"]` or
`Literal["sync"]`, using `ASYNC_MODE` or `SYNC_MODE` from `constants`. The suite
protocols expose this discriminator as a read-only property. A concrete adapter
can implement it with a class attribute, for example:

```python
from typing import Literal

from foghttp_benchmark.constants import ASYNC_MODE


class MyAsyncAdapter:
    mode: Literal["async"] = ASYNC_MODE
    # Implement the suite protocol's operations, close and optional stats.
```

Streaming, one-upstream and proxy load dispatch inspect the adapter's mode.
They accept no separate mode argument and narrow the adapter before entering
the existing workers. Requests and resources retain their nominal
`AsyncClientAdapter` / `SyncClientAdapter` dispatch. Request builder and client
creation narrow the specification before invoking the factory or crossing the
thread boundary. Lifecycle workers also check the selected specification's
mode before constructing the adapter.

Sync load still runs through `asyncio.to_thread` with the existing worker pool.
The entire sync request-builder case and sync creation operation stay inside
their existing thread boundary. Factory calls, warmup, sampling, measured
intervals, statistics collection and cleanup retain their previous order.
There is no adapter wrapper allocation in a measured interval. Lifecycle
construction timing still surrounds the factory call; unsettled cancellation
workers retain their existing forced-reap behavior.

Factories and adapters are internal typed contracts. They do not validate
third-party signatures at runtime. Client libraries themselves do not need a
mode attribute or a statistics API: their benchmark adapters own these members.

## Optional statistics

Adapters that expose statistics return `ClientStats | None`. Unsupported or
unavailable observations remain `None`; available statistics retain their real
values, including zero. Request-builder adapters have no statistics contract.
This change adds no mandatory statistics API to a client library and does not
change saved report schemas, CLI arguments or existing artifacts.

## Migration and verification

Replace internal calls such as
`StreamingClientSpec(name=..., mode="async", factory=...)` with
`AsyncStreamingClientSpec(name=..., factory=...)`. Use the sync constructor for
a sync factory. Combined `*ClientSpec` names remain annotation types and are
not constructors. Remove the independent `mode` argument from specialized
`run_*_load` calls; adapter test doubles must implement the matching mode.

Run `uv run --locked --extra dev pytest -q tests/client_modes` for positive and
negative mypy contracts and dispatch/lifecycle regressions. The ordinary
strict package check remains `uv run --locked --extra dev mypy`.
