from collections.abc import Iterable

from foghttp_benchmark.statistics import merge_error_types
import pytest


@pytest.mark.parametrize("values", [[], [{}]], ids=["empty-input", "empty-counter"])
def test_merge_empty_error_types(values: Iterable[dict[str, int]]) -> None:
    assert merge_error_types(values) == {}


def test_merge_error_types_consumes_generator_and_accumulates_shared_keys() -> None:
    values = [{"TimeoutError": 2}, {"ReadError": 3, "TimeoutError": 4}, {"TimeoutError": 1}]

    assert merge_error_types(value for value in values) == {"TimeoutError": 7, "ReadError": 3}
    assert values == [{"TimeoutError": 2}, {"ReadError": 3, "TimeoutError": 4}, {"TimeoutError": 1}]


def test_merge_error_types_retains_nonpositive_counts_and_first_seen_order() -> None:
    result = merge_error_types(
        [
            {"TimeoutError": 3, "CancelledError": 0},
            {"ReadError": -2, "TimeoutError": -3},
        ],
    )

    assert result == {"TimeoutError": 0, "CancelledError": 0, "ReadError": -2}
    assert list(result) == ["TimeoutError", "CancelledError", "ReadError"]


def test_merged_error_counter_does_not_alias_single_input() -> None:
    original = {"TimeoutError": 2}
    result = merge_error_types([original])
    result["TimeoutError"] += 1
    result["ReadError"] = 4

    assert original == {"TimeoutError": 2}
    assert result == {"TimeoutError": 3, "ReadError": 4}
