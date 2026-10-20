from dataclasses import replace
import json
from pathlib import Path

from foghttp_benchmark.isolation.models import ChildProcessResult, ChildResourcePeaks
from foghttp_benchmark.reports import write_reports
from tests.isolation.args_factory import benchmark_args
from tests.isolation.report_rows import request_result


def request_child(directory: Path, *, sequence: int, client: str) -> ChildProcessResult:
    write_reports([request_result(client)], {}, benchmark_args(directory))
    return ChildProcessResult(
        sequence=sequence,
        client=client,
        scenario=None,
        output_dir=str(directory),
        report_path=str(directory / "latest.json"),
        command=["python", "-m", "foghttp_benchmark._child", "--clients", client],
        returncode=0,
        duration_s=1.0,
        peaks=ChildResourcePeaks(rss_mb=10.0, threads=1, fds=4),
        stdout_tail="child stdout retained",
        stderr_tail="child stderr retained",
    )


def corrupted_child(
    directory: Path,
    *,
    section: str,
    field: str,
    value: object,
) -> tuple[ChildProcessResult, bytes]:
    child = request_child(directory, sequence=2, client="httpx")
    path = Path(child.report_path or "")
    payload = json.loads(path.read_text())
    if section == "metadata":
        payload[section][field] = value
    else:
        payload[section][0][field] = value
    path.write_text(json.dumps(payload))
    return replace(child, stderr_tail="schema-corrupted report retained"), path.read_bytes()
