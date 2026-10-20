import json
from pathlib import Path
import subprocess
import sys

import pytest

from tests.architecture.rules import PRESENTATION, ROOT, UI, within, writer_reference


@pytest.mark.parametrize(
    "module",
    [
        f"{ROOT}.statistics",
        f"{ROOT}.rendering",
        f"{ROOT}.report_publication",
        f"{ROOT}.report_schema.decoding",
        f"{ROOT}.validity.classification",
        f"{ROOT}.streaming.attribution_window",
        f"{ROOT}.streaming.attribution_validation",
    ],
)
def test_cold_import_does_not_load_writers_or_execution(module: str) -> None:
    probe = Path(__file__).with_name("cold_import.py.txt")
    result = subprocess.run(  # noqa: S603 - fixed local probe and parametrized project module names.
        [sys.executable, str(probe), module],
        cwd=probe.parents[2],
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    )
    loaded = json.loads(result.stdout)
    unexpected = [
        target
        for target in loaded
        if target != module
        and (
            writer_reference(target)
            or any(within(target, prefix) for prefix in (*UI, *PRESENTATION, f"{ROOT}.application"))
            or target.rsplit(".", maxsplit=1)[-1] in {"runner", "load"}
        )
    ]

    assert unexpected == [], f"{module} loaded {unexpected}"
