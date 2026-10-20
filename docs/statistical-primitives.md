# Statistical primitives

`foghttp_benchmark/statistics.py` owns the three shared ordinary benchmark
primitives: `coefficient_of_variation`, `percentile` and `merge_error_types`.
It depends only on the standard library and the existing
`MIN_VARIATION_SAMPLES` constant. It imports no runners, suite reports, adapters
or validity classification.

This module consolidates equivalent calculations. Suite grouping, aggregation,
baseline ratios, resource coverage and validity policies keep their existing
owners. JSON fields, units and schema versions are unchanged.

## Coefficient of variation

`coefficient_of_variation(values: Sequence[float]) -> float` returns sample
standard deviation divided by the mean, multiplied by 100. It uses the existing
standard-library `statistics.mean` and `statistics.stdev` operations.

The ordinary contract remains:

- Fewer than `MIN_VARIATION_SAMPLES` observations, currently two, return `0.0`.
- A zero mean returns `0.0`.
- Other inputs retain the signed mean, without absolute values, filtering or
  rounding. For example, `[10, 20, 30]` has a sample CV of 50 percent.
- The input is a repeatable sequence; it is not consumed as a one-pass iterator
  or modified by the calculation. Resource reporting continues to accept a
  `Sequence`, including tuples.

Lifecycle and async-bytes attribution retain `streaming.lifecycle_aggregation.cv_optional`.
That function requires at least `LIFECYCLE_MIN_VARIATION_REPETITIONS`, currently
three, and returns `None` for insufficient observations or zero mean. Its
unavailable result is not replaced by ordinary CV's zero. Optional resource
aggregation and completeness policies are also unchanged.

## Percentile

`percentile(values: list[float], pct: float) -> float` expects values already
sorted by the caller. It selects an observed value using the unchanged index:

```text
min(n - 1, max(0, round((pct / 100) * (n - 1))))
```

Empty input returns `0.0`. Python's existing ties-to-even `round` and index
clamping are retained. There is no interpolation or internal sorting. For
example, the 50th percentile of `[10, 20, 30, 40]` selects index two, value 30.
The output has the same units as the samples; latency callers supply their
existing millisecond values.

Request, creation, resource, one-upstream, request-builder, proxy and ordinary
streaming measurement code still sorts its samples before calling this helper.
Lifecycle's optional `quantile` retains its own contract and owner.

## Error counters

`merge_error_types(values: Iterable[dict[str, int]]) -> dict[str, int]` sums
counts for equal names into a fresh plain dictionary. The outer iterable is
consumed once, so generator inputs remain supported. Source dictionaries are
not modified or aliased by the result.

Keys retain their first-seen insertion order, including keys whose totals are
zero or negative. No counters are filtered or normalized. Validation and error
classification remain separate responsibilities.

## Import migration

Consumers import these functions directly from the shared owner:

```python
from foghttp_benchmark.statistics import coefficient_of_variation, merge_error_types, percentile
```

The former definitions in request and suite reporting modules have been removed.
The two primitive exports from `resource.reporting.metrics.__all__` have also
been removed; import them from `foghttp_benchmark.statistics` instead. Other
resource-specific metric helpers remain in their original module.

There are no compatibility wrappers or new dependencies. This extraction does
not change measurement algorithms, CLI arguments or report interpretation and
does not require a benchmark rebaseline.
