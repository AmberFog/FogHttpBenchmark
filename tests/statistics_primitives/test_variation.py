from collections.abc import Sequence
from math import sqrt

from foghttp_benchmark.statistics import coefficient_of_variation
import pytest


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        pytest.param([], 0.0, id="empty"),
        pytest.param([7.0], 0.0, id="single"),
        pytest.param([4.0, 4.0, 4.0], 0.0, id="identical"),
        pytest.param([-1.0, 0.0, 1.0], 0.0, id="zero-mean"),
        pytest.param([1.0, 3.0], 50.0 * sqrt(2), id="two-samples-use-sample-deviation"),
        pytest.param([1.0, 2.0, 3.0], 50.0, id="three-samples"),
        pytest.param((1.0, 2.0, 3.0), 50.0, id="tuple-sequence"),
        pytest.param([-3.0, -1.0], -50.0 * sqrt(2), id="negative-mean-retains-sign"),
    ],
)
def test_variation_preserves_existing_numerical_convention(values: Sequence[float], expected: float) -> None:
    assert coefficient_of_variation(values) == pytest.approx(expected)
