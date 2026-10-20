from pathlib import Path

import pytest

from foghttp_benchmark.compare.loading import load_benchmark_report
from foghttp_benchmark.compare.reports import build_comparison
from foghttp_benchmark.measurement_timing import TimingScope, current_timing_scope, report_timing_scope
from tests.compare.factories import timing_request_report


REQUESTS_PER_SECOND = 100.0


@pytest.mark.parametrize(
    ("suite", "scope"),
    [
        ("requests", "requests-load-only-v2"),
        ("compressed-response", "requests-load-only-v2"),
        ("one-upstream", "one-upstream-load-only-v2"),
        ("proxy-connect", "proxy-connect-load-only-v2"),
        ("resource-backpressure", "resource-backpressure-load-only-v2"),
        ("client-creation", "client-creation-operation-v1"),
        ("request-builder", "request-builder-load-only-v1"),
        ("response-streaming", "load-only-v2"),
    ],
)
def test_current_scope_is_explicit_and_supported(suite: str, scope: str) -> None:
    assert current_timing_scope(suite).value == scope
    assert report_timing_scope(suite, {"timing_scope": scope}, []) == scope


@pytest.mark.parametrize(
    ("suite", "scope"),
    [
        ("requests", "requests-sampler-inclusive-v1"),
        ("compressed-response", "requests-sampler-inclusive-v1"),
        ("one-upstream", "one-upstream-sampler-inclusive-v1"),
        ("proxy-connect", "proxy-connect-sampler-inclusive-v1"),
        ("resource-backpressure", "resource-backpressure-sampler-inclusive-v1"),
        ("response-streaming", "legacy-sampler-v1"),
    ],
)
def test_explicit_known_legacy_scope_is_readable(suite: str, scope: str) -> None:
    assert report_timing_scope(suite, {"timing_scope": scope}, []) == scope


@pytest.mark.parametrize("scope", [TimingScope.REQUESTS.value, TimingScope.LEGACY_REQUESTS.value])
def test_same_supported_scope_allows_comparison(tmp_path: Path, scope: str) -> None:
    old = timing_request_report(tmp_path, "old.json", scope)
    new = timing_request_report(tmp_path, "new.json", scope)

    comparison = build_comparison(old, new, focus_client="foghttp", top_n=1)

    assert comparison.overall.rows == 1
    assert comparison.overall.primary_median_ratio == 1
    assert not comparison.validity.blocks_strong_conclusions


def test_current_and_sampler_inclusive_legacy_cannot_compare(tmp_path: Path) -> None:
    old = timing_request_report(tmp_path, "old.json", TimingScope.LEGACY_REQUESTS.value)
    new = timing_request_report(tmp_path, "new.json", TimingScope.REQUESTS.value)

    with pytest.raises(ValueError, match="timing scopes differ"):
        build_comparison(old, new, focus_client="foghttp", top_n=1)


@pytest.mark.parametrize("scope", [None, "future-timing-v99", TimingScope.ONE_UPSTREAM.value])
def test_unknown_or_wrong_suite_scope_loads_but_cannot_compare(tmp_path: Path, scope: str | None) -> None:
    old = timing_request_report(tmp_path, "old.json", scope)
    new = timing_request_report(tmp_path, "new.json", scope)

    assert load_benchmark_report(old).rows[0].primary_value == REQUESTS_PER_SECOND
    with pytest.raises(ValueError, match="Unknown or unsupported timing scope"):
        build_comparison(old, new, focus_client="foghttp", top_n=1)


@pytest.mark.parametrize("scope", [TimingScope.STREAMING.value, TimingScope.LEGACY_STREAMING.value])
def test_explicit_ordinary_streaming_row_scope_identifies_historical_contract(scope: str) -> None:
    metadata: dict[str, object] = {"timing_scopes": [scope]}
    assert report_timing_scope("response-streaming", metadata, [{"timing_scope": scope}]) == scope


def test_empty_streaming_report_requires_explicit_scope_for_skipped_diagnostics() -> None:
    metadata: dict[str, object] = {"timing_scope": "load-only-v2", "timing_scopes": []}
    assert report_timing_scope("response-streaming", metadata, []) == TimingScope.STREAMING
    with pytest.raises(ValueError, match="Unknown or unsupported timing scope"):
        report_timing_scope("response-streaming", {"timing_scopes": []}, [])


@pytest.mark.parametrize(
    ("metadata", "rows"),
    [
        ({"timing_scopes": ["load-only-v2"]}, [{}]),
        ({"timing_scopes": ["load-only-v2"]}, [{"timing_scope": "legacy-sampler-v1"}]),
        ({"timing_scope": "load-only-v2"}, [{"timing_scope": "legacy-sampler-v1"}]),
        ({"timing_scope": "load-only-v2"}, [{"timing_scope": "load-only-v2"}, {}]),
        ({"timing_scope": "load-only-v2"}, [{"timing_scope": "load-only-v2"}, {"timing_scope": "legacy-sampler-v1"}]),
        ({"timing_scope": "load-only-v2", "timing_scopes": ["load-only-v2", "legacy-sampler-v1"]}, []),
    ],
)
def test_contradictory_or_missing_streaming_scope_is_rejected(
    metadata: dict[str, object],
    rows: list[dict[str, object]],
) -> None:
    with pytest.raises(ValueError, match="timing scope"):
        report_timing_scope("response-streaming", metadata, rows)


@pytest.mark.parametrize("profile", ["async-bytes", "lifecycle"])
def test_research_profile_cannot_be_relabelled_as_ordinary_streaming(profile: str) -> None:
    with pytest.raises(ValueError, match="Unknown or unsupported timing scope"):
        report_timing_scope(
            "response-streaming",
            {"timing_scope": "load-only-v2"},
            [{"profile": profile}],
        )
