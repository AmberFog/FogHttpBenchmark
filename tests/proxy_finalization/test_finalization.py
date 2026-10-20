from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict, replace
from itertools import permutations

import pytest

from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.proxy_connect.finalization import (
    AmbiguousDirectBaselineError,
    finalize_proxy_connect_rows,
)
from foghttp_benchmark.proxy_connect.models import ProxyConnectAggregateRow
from foghttp_benchmark.proxy_connect.reports import rows_with_direct_ratios
from tests.proxy_finalization.support import aggregate_row, finalize_json, finalize_typed


FINALIZERS = (finalize_json, finalize_typed)
Finalizer = Callable[[list[ProxyConnectAggregateRow]], list[JsonObject]]


def test_typed_and_json_finalization_preserve_fields_and_recompute_cross_row_ratios() -> None:
    baseline = aggregate_row()
    proxy = aggregate_row(case="proxy-connect", config="explicit", throughput=70.0)
    cold = aggregate_row(case="cold-direct", lifecycle="cold-client", throughput=20.0)
    rows = [proxy, cold, baseline]
    before = deepcopy(rows)
    expected = [
        {**asdict(proxy), "direct_ratio": 0.7},
        {**asdict(cold), "direct_ratio": 0.2},
        {**asdict(baseline), "direct_ratio": 1.0},
    ]

    assert finalize_json(rows) == expected
    assert finalize_typed(rows) == expected
    assert rows == before


@pytest.mark.parametrize("finalizer", FINALIZERS)
@pytest.mark.parametrize(
    "other_baseline",
    [
        replace(aggregate_row(), mode="sync"),
        replace(aggregate_row(), client="httpx"),
        replace(aggregate_row(), target_scheme="http"),
        replace(aggregate_row(), concurrency=20),
    ],
    ids=("mode", "client", "target-scheme", "concurrency"),
)
def test_baseline_key_keeps_all_four_dimensions(
    finalizer: Finalizer,
    other_baseline: ProxyConnectAggregateRow,
) -> None:
    rows = [aggregate_row(case="proxy-connect", config="explicit", throughput=70.0), other_baseline]

    finalized = finalizer(rows)

    assert finalized[0]["direct_ratio"] is None
    assert finalized[1]["direct_ratio"] == 1.0


@pytest.mark.parametrize("finalizer", FINALIZERS)
def test_request_limit_is_not_silently_added_to_baseline_key(finalizer: Finalizer) -> None:
    baseline = aggregate_row()
    proxy = replace(aggregate_row(case="proxy-connect", config="explicit", throughput=70.0), request_limit=20)

    assert finalizer([baseline, proxy])[1]["direct_ratio"] == pytest.approx(0.7)


@pytest.mark.parametrize("finalizer", FINALIZERS)
@pytest.mark.parametrize("config", ("explicit", "trust-env"))
def test_proxy_configuration_cannot_supply_baseline(finalizer: Finalizer, config: str) -> None:
    rows = [aggregate_row(config=config)]

    assert finalizer(rows)[0]["direct_ratio"] is None


@pytest.mark.parametrize("finalizer", FINALIZERS)
def test_cold_direct_client_cannot_supply_baseline(finalizer: Finalizer) -> None:
    rows = [aggregate_row(lifecycle="cold-client")]

    assert finalizer(rows)[0]["direct_ratio"] is None


@pytest.mark.parametrize("finalizer", FINALIZERS)
@pytest.mark.parametrize("throughput", (0.0, -1.0))
def test_nonpositive_baseline_does_not_produce_ratios(finalizer: Finalizer, throughput: float) -> None:
    rows = [aggregate_row(throughput=throughput), aggregate_row(case="proxy-connect", config="explicit")]

    assert [row["direct_ratio"] for row in finalizer(rows)] == [None, None]


@pytest.mark.parametrize("finalizer", FINALIZERS)
@pytest.mark.parametrize(
    "other_baseline",
    [
        replace(aggregate_row(), request_limit=20),
        replace(aggregate_row(), group="other-group"),
        replace(aggregate_row(), case="other-case"),
    ],
    ids=("request-limit", "group", "case"),
)
def test_distinct_direct_aggregates_cannot_silently_compete_for_baseline(
    finalizer: Finalizer,
    other_baseline: ProxyConnectAggregateRow,
) -> None:
    baseline = aggregate_row()
    proxy = aggregate_row(case="proxy-connect", config="explicit")
    for rows in permutations((baseline, proxy, other_baseline)):
        before = deepcopy(rows)
        with pytest.raises(AmbiguousDirectBaselineError, match="Ambiguous direct baseline"):
            finalizer(list(rows))
        assert rows == before


@pytest.mark.parametrize("finalizer", FINALIZERS)
def test_duplicate_identity_is_rejected_before_any_ambiguous_baseline(finalizer: Finalizer) -> None:
    baseline = aggregate_row()
    conflicting = replace(baseline, ok_req_s_median=70.0)
    distinct_baseline = replace(baseline, case="other-direct")
    for rows in permutations((baseline, distinct_baseline, conflicting)):
        with pytest.raises(ValueError, match="Duplicate aggregate identity") as error:
            finalizer(list(rows))
        assert not isinstance(error.value, AmbiguousDirectBaselineError)


def test_json_finalization_returns_new_rows_without_mutating_inputs() -> None:
    rows = [asdict(aggregate_row()), asdict(aggregate_row(case="proxy-connect", config="explicit"))]
    before = deepcopy(rows)

    finalized = finalize_proxy_connect_rows(rows)

    assert rows == before
    assert finalized is not rows
    assert all(new is not old for new, old in zip(finalized, rows, strict=True))


def test_typed_finalization_returns_replaced_rows_without_mutating_inputs() -> None:
    rows = [aggregate_row(), aggregate_row(case="proxy-connect", config="explicit")]
    before = deepcopy(rows)

    finalized = rows_with_direct_ratios(rows)

    assert rows == before
    assert finalized is not rows
    assert all(new is not old for new, old in zip(finalized, rows, strict=True))


@pytest.mark.parametrize("finalizer", FINALIZERS)
def test_empty_aggregate_is_supported(finalizer: Finalizer) -> None:
    assert finalizer([]) == []
