import json
from pathlib import Path
from typing import cast

from foghttp_benchmark.isolation.models import ChildProcessResult
from foghttp_benchmark.models import JsonObject
from tests.isolation.test_reports import child_result, write_child_report


def child_payload(child: ChildProcessResult) -> JsonObject:
    return cast("JsonObject", json.loads(Path(child.report_path or "").read_text()))


def proxy_children(directory: Path, rows: list[JsonObject]) -> list[ChildProcessResult]:
    children = []
    for sequence, row in enumerate(rows, start=1):
        path = write_child_report(
            directory / f"child-{sequence}",
            client="foghttp",
            suite="proxy-connect",
            aggregate=[row],
            runs=[],
            skipped={},
        )
        children.append(child_result(sequence, "foghttp", path))
    return children
