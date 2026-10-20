# CLI configuration contract

The CLI resolves omitted options once, before validation and process planning.
An explicit value is preserved even when it equals the common default. For
example, streaming `--requests 2000` means 2000; proxy `--warmup 200` means 200.
Existing validation and research-profile caps still apply. Explicit unsupported
scenarios fail validation instead of selecting the suite's default scenarios.

## Defaults for omitted options

| Suite | Requests | Warmup | Concurrency | Scenarios |
| --- | ---: | ---: | --- | --- |
| `requests` | 2000 | 200 | `1,10,50,100` | `DEFAULT_SCENARIOS` |
| `client-creation` | unused | 200 | unused | unused |
| `resource-backpressure` | 2000 | 200 | `1,10,50,100` | `DEFAULT_RESOURCE_SCENARIOS` |
| `one-upstream` | 2000 | 200 | `1,10,50,100` | `DEFAULT_ONE_UPSTREAM_SCENARIOS` |
| `request-builder` | unused | 200 | unused | `DEFAULT_REQUEST_BUILDER_SCENARIOS` |
| `compressed-response` | 2000 | 200 | `1,10,50,100` | `DEFAULT_COMPRESSED_RESPONSE_SCENARIOS` |
| `response-streaming` | 200 | 200 | `1,10,50,100` | `DEFAULT_STREAMING_SCENARIOS` |
| `proxy-connect` | 100 | 20 | `1,10,50` | `DEFAULT_PROXY_CONNECT_SCENARIOS` |

Scenario lists are defined in [constants.py](../foghttp_benchmark/constants.py).
Unused fields retain their common CLI values in metadata. All other ordinary
defaults are unchanged, including iterations 100 and repeats 3.

The opt-in `lifecycle` and `async-bytes` streaming profiles keep their existing
omitted defaults: clients `foghttp,httpx`, concurrency `1,10`, requests 20,
warmup 2, iterations 5 and repeats 3. Modes are `async,sync` for `lifecycle`
and `async` for `async-bytes`. Scenarios are `first-chunk-close-1m,stream-1m`
and `stream-1m`, respectively. Explicit options override these defaults subject
to the existing profile limits. Explicit `--streaming-*` diagnostic options
still require `--streaming-profile async-bytes`.

## Programmatic migration

`BenchmarkArgs` contains concrete effective values. `run_benchmark`, suite
functions and isolated children use those values without another default pass.
The dataclass and JSON layout are unchanged; the correction removes the old
value-equality heuristic. Previously, some programmatic calls containing common
defaults silently selected different workloads.

Callers that intended the old suite-specific defaults must select them before
constructing `BenchmarkArgs`, or use the public CLI with omitted options. For
example, when deriving a streaming configuration from an existing configuration:

```python
from dataclasses import replace

from foghttp_benchmark.constants import (
    DEFAULT_STREAMING_REQUESTS,
    DEFAULT_STREAMING_SCENARIOS,
    RESPONSE_STREAMING_SUITE,
)

streaming_args = replace(
    existing_args,
    suite=RESPONSE_STREAMING_SUITE,
    requests=DEFAULT_STREAMING_REQUESTS,
    scenarios=DEFAULT_STREAMING_SCENARIOS,
)
```

Apply the same explicit choice to proxy requests, warmup, concurrency and
scenarios. There is no sentinel value inside `BenchmarkArgs` for "omitted".

The isolated parent passes every effective option to the internal `_child`
entrypoint. Its parser defaults are literal common values for direct internal
invocation; it does not reproduce the public CLI's suite/profile default pass.
Child client/scenario selections and output paths reflect their partition of
the parent plan. Other values agree across the parent configuration, generated
command, child configuration and report metadata. Historical reports are not
rewritten.
