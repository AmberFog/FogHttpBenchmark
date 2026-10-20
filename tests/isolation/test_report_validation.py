from pathlib import Path
import re

import pytest

from foghttp_benchmark.application.composition import get_suite
from foghttp_benchmark.isolation.reports import write_isolation_report
from tests.isolation.args_factory import benchmark_args
from tests.isolation.report_validation_support import corrupted_child, request_child


@pytest.mark.parametrize(
    ("section", "field", "value", "error_path"),
    [
        ("aggregate", "ok_req_s_median", None, "aggregate[0].ok_req_s_median"),
        ("aggregate", "ok_req_s_median", True, "aggregate[0].ok_req_s_median"),
        ("aggregate", "errors_total", -1, "aggregate[0].errors_total"),
        ("aggregate", "errors_total", 0.5, "aggregate[0].errors_total"),
        ("aggregate", "error_types", {"RuntimeError": 1}, "aggregate[0].error_types"),
        ("runs", "ok_requests", False, "runs[0].ok_requests"),
        ("runs", "errors", "0", "runs[0].errors"),
        ("runs", "warmup_error_types", {"RuntimeError": 1}, "runs[0].warmup_error_types"),
        ("metadata", "suite", "future-suite", "metadata.suite"),
    ],
)
def test_isolation_rejects_a_corrupt_child_before_publishing_successful_merge(
    tmp_path: Path,
    section: str,
    field: str,
    value: object,
    error_path: str,
) -> None:
    first = request_child(tmp_path / "valid-child", sequence=1, client="foghttp")
    second, source = corrupted_child(tmp_path / "corrupt-child", section=section, field=field, value=value)
    first_path = Path(first.report_path or "")
    second_path = Path(second.report_path or "")
    valid_source = first_path.read_bytes()
    parent = tmp_path / "parent"

    with pytest.raises(ValueError, match=re.escape(error_path)):
        write_isolation_report(
            benchmark_args(parent),
            [first, second],
            {},
            finalizer=get_suite("requests").finalize_report,
            child_cooldown_s=0.0,
        )

    assert first_path.read_bytes() == valid_source
    assert second_path.read_bytes() == source
    assert second.stderr_tail == "schema-corrupted report retained"
    assert second.stdout_tail == "child stdout retained"
    assert second.command[-1] == "httpx"
    assert not list(parent.glob("*.json"))
    assert not list(parent.glob("*.md"))
