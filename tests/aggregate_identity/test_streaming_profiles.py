from copy import deepcopy
from pathlib import Path

import pytest

from foghttp_benchmark.compare.loading import load_benchmark_report
from tests.aggregate_identity.factories import (
    lifecycle_report,
    lifecycle_row,
    replace_aggregate,
    saved_aggregate,
)
from tests.streaming.attribution_report_factory import write_report as write_attribution_report


PROFILE_ROW_COUNT = 2


def test_lifecycle_configuration_mapping_order_does_not_hide_duplicates(tmp_path: Path) -> None:
    first = lifecycle_row()
    second = {
        **first,
        "configuration": {
            "timeouts": {"read": 2, "connect": 1},
            "server_write_bytes": 128,
            "body_bytes": 1024,
        },
    }
    path = lifecycle_report(tmp_path, [first, second])

    with pytest.raises(ValueError, match="Duplicate aggregate identity"):
        load_benchmark_report(path)


def test_lifecycle_configuration_values_remain_distinct_identities(tmp_path: Path) -> None:
    first = lifecycle_row()
    second = {**first, "configuration": {"body_bytes": 2048, "server_write_bytes": 128}}
    path = lifecycle_report(tmp_path, [first, second])

    report = load_benchmark_report(path)

    assert len(report.rows) == PROFILE_ROW_COUNT
    assert report.rows[0].identity != report.rows[1].identity


@pytest.mark.parametrize("conflicting", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_async_bytes_duplicate_rejected_before_cached_raw_validity_can_publish_it(
    tmp_path: Path,
    *,
    conflicting: bool,
    reverse: bool,
) -> None:
    path = write_attribution_report(tmp_path, with_provenance=True)
    assert load_benchmark_report(path).validity.can_compare is True
    rows = saved_aggregate(path)
    duplicate = deepcopy(rows[0])
    if conflicting:
        duplicate["verified_bytes_s_median"] = 1.0
    rows.append(duplicate)
    if reverse:
        rows.reverse()
    replace_aggregate(path, rows)

    with pytest.raises(ValueError, match="Duplicate aggregate identity"):
        load_benchmark_report(path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("condition_fingerprint", "f" * 64),
        ("primary_metric", "ok_streams_s_median"),
        ("throughput_scope", "legacy-observed-v1"),
        ("timing_scope", "legacy-sampler-v1"),
    ],
)
def test_distinct_async_bytes_identity_does_not_bypass_raw_recomputation(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    path = write_attribution_report(tmp_path, with_provenance=True)
    assert load_benchmark_report(path).validity.can_compare is True
    rows = saved_aggregate(path)
    rows.append({**deepcopy(rows[0]), field: value})
    replace_aggregate(path, rows)

    report = load_benchmark_report(path)

    assert len(report.rows) == PROFILE_ROW_COUNT
    assert report.rows[0].identity != report.rows[1].identity
    assert report.validity.can_compare is False
    assert "attribution_raw_evidence_invalid" in {reason.code for reason in report.validity.reasons}
