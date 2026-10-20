from foghttp_benchmark.statistics import percentile
import pytest


@pytest.mark.parametrize(
    ("values", "pct", "expected"),
    [
        pytest.param([], 50.0, 0.0, id="empty"),
        pytest.param([7.0], 200.0, 7.0, id="single"),
        pytest.param([10.0, 20.0, 30.0, 40.0], -25.0, 10.0, id="below-zero-clamps"),
        pytest.param([10.0, 20.0, 30.0, 40.0], 0.0, 10.0, id="zero"),
        pytest.param([10.0, 20.0, 30.0, 40.0], 100.0, 40.0, id="hundred"),
        pytest.param([10.0, 20.0, 30.0, 40.0], 125.0, 40.0, id="above-hundred-clamps"),
        pytest.param([10.0, 20.0], 50.0, 10.0, id="half-index-rounds-to-zero"),
        pytest.param([10.0, 20.0, 30.0, 40.0], 50.0, 30.0, id="one-and-half-rounds-to-two"),
        pytest.param([10.0, 20.0, 30.0, 40.0, 50.0, 60.0], 50.0, 30.0, id="two-and-half-rounds-to-two"),
        pytest.param([10.0, 20.0, 30.0, 40.0], 80.0, 30.0, id="selects-sample-without-interpolation"),
    ],
)
def test_percentile_selects_clamped_ties_to_even_index(values: list[float], pct: float, expected: float) -> None:
    assert percentile(values, pct) == expected


def test_percentile_leaves_sorting_to_caller_without_mutating_samples() -> None:
    samples = [30.0, 10.0, 20.0]
    unsorted_expected = 10.0
    sorted_expected = 20.0

    assert percentile(samples, 50.0) == unsorted_expected
    assert percentile(sorted(samples), 50.0) == sorted_expected
    assert samples == [30.0, 10.0, 20.0]
