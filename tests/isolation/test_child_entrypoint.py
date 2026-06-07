from pathlib import Path

import pytest

from foghttp_benchmark._child import build_child_args, build_parser
from foghttp_benchmark.constants import REQUEST_BUILDER_SUITE


def test_child_entrypoint_builds_benchmark_args_without_public_isolation_switch(tmp_path: Path) -> None:
    parser = build_parser()

    namespace = parser.parse_args(
        [
            "--suite",
            REQUEST_BUILDER_SUITE,
            "--clients",
            "foghttp",
            "--modes",
            "async",
            "--requests",
            "2",
            "--warmup",
            "0",
            "--repeats",
            "1",
            "--output-dir",
            str(tmp_path),
            "--scenarios",
            "absolute-url",
            "--no-progress",
        ],
    )

    args = build_child_args(namespace)

    assert args.suite == REQUEST_BUILDER_SUITE
    assert args.clients == "foghttp"
    assert args.scenarios == "absolute-url"
    assert args.output_dir == str(tmp_path)
    assert namespace.show_progress is False


def test_child_entrypoint_rejects_isolation_switch() -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["--clients", "foghttp", "--isolation", "none"])
