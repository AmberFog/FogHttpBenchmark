import json
from pathlib import Path
from typing import cast

from foghttp_benchmark.isolation.models import ChildProcessResult, ChildResourcePeaks
from foghttp_benchmark.measurement_timing import current_timing_scope
from foghttp_benchmark.models import JsonObject
from tests.report_schema.ordinary_fixtures import ordinary_aggregate, ordinary_run


def report_payload(suite: str = "requests") -> JsonObject:
    return {
        "metadata": {"suite": suite, "timing_scope": current_timing_scope(suite)},
        "aggregate": [ordinary_aggregate(suite)],
        "runs": [ordinary_run(suite)],
    }


def payload_metadata(payload: JsonObject) -> JsonObject:
    return cast("JsonObject", payload["metadata"])


def payload_rows(payload: JsonObject, collection: str = "aggregate") -> list[JsonObject]:
    return cast("list[JsonObject]", payload[collection])


def write_payload(directory: Path, payload: JsonObject) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "latest.json"
    path.write_text(json.dumps(payload))
    return path


def child_process_result(path: Path) -> ChildProcessResult:
    return ChildProcessResult(
        sequence=1,
        client="foghttp",
        scenario=None,
        output_dir=str(path.parent),
        report_path=str(path),
        command=["python", "-m", "foghttp_benchmark"],
        returncode=0,
        duration_s=1.0,
        peaks=ChildResourcePeaks(rss_mb=None, threads=None, fds=None),
        stdout_tail="child output retained",
        stderr_tail="child diagnostics retained",
    )
