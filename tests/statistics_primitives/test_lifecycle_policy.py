from math import sqrt

import pytest

from foghttp_benchmark.statistics import coefficient_of_variation
from foghttp_benchmark.streaming.lifecycle_aggregation import cv_optional


@pytest.mark.parametrize(
    ("values", "ordinary_expected"),
    [
        pytest.param([], 0.0, id="empty"),
        pytest.param([1.0], 0.0, id="one-repetition"),
        pytest.param([1.0, 3.0], 50.0 * sqrt(2), id="two-repetitions"),
        pytest.param([-1.0, 0.0, 1.0], 0.0, id="zero-mean"),
    ],
)
def test_lifecycle_unavailable_variation_retains_its_distinct_policy(
    values: list[float],
    ordinary_expected: float,
) -> None:
    assert coefficient_of_variation(values) == pytest.approx(ordinary_expected)
    assert cv_optional(values) is None


def test_lifecycle_variation_becomes_available_at_three_repetitions() -> None:
    values = [1.0, 2.0, 3.0]

    assert cv_optional(values) == pytest.approx(50.0)
    assert cv_optional(values) == pytest.approx(coefficient_of_variation(values))
