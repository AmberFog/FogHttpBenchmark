import json
from pathlib import Path
import re

import pytest

from foghttp_benchmark.application.composition import get_suite
from foghttp_benchmark.isolation.reports import write_isolation_report
from foghttp_benchmark.models import ClientCreationResult
from foghttp_benchmark.report_schema.decoding import load_report
from tests.creation_error_events.actions import creation_args, write_failure_child


@pytest.mark.parametrize(
    ("section", "field", "value"),
    (
        ("aggregate", "errors_total", 13),
        ("runs", "errors", 7),
        ("runs", "errors", 0.5),
        ("runs", "error_types", {"RuntimeError": 1}),
    ),
)
def test_invalid_creation_event_counts_are_rejected_before_parent_publication(
    tmp_path: Path,
    request_close_result: ClientCreationResult,
    section: str,
    field: str,
    value: object,
) -> None:
    child = write_failure_child(tmp_path / "child", request_close_result)
    path = Path(child.report_path or "")
    payload = json.loads(path.read_text())
    payload[section][0][field] = value
    path.write_text(json.dumps(payload))
    source = path.read_bytes()
    parent = tmp_path / "parent"
    error_path = re.escape(f"{section}[0].{field}")

    with pytest.raises(ValueError, match=error_path):
        load_report(path)
    with pytest.raises(ValueError, match=error_path):
        write_isolation_report(
            creation_args(parent),
            [child],
            {},
            child_cooldown_s=0.0,
            finalizer=get_suite("client-creation").finalize_report,
        )

    assert path.read_bytes() == source
    assert child.stdout_tail == "offline diagnostic stdout"
    assert child.stderr_tail == "offline diagnostic stderr"
    assert not list(parent.glob("*.json"))
    assert not list(parent.glob("*.md"))
