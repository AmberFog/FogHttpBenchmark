from importlib import import_module
from types import SimpleNamespace

import pytest

from tests.publication_consumers.support import REPORT_TIMESTAMP
from tests.resource_metrics.cases import RESOURCE_REPORT_CASES, ResourceReportCase


@pytest.fixture(params=RESOURCE_REPORT_CASES, ids=lambda case: case.suite)
def report_case(request: pytest.FixtureRequest) -> ResourceReportCase:
    return request.param


@pytest.fixture(autouse=True)
def fixed_display_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    modules = {case.writer.func.__module__ for case in RESOURCE_REPORT_CASES}
    modules.add("foghttp_benchmark.isolation.reports")
    for name in modules:
        module = import_module(name)
        monkeypatch.setattr(module, "time", SimpleNamespace(strftime=lambda _format: REPORT_TIMESTAMP))
        monkeypatch.setattr(module, "package_versions", lambda: {"foghttp": "0.4.2-fixture"})
    monkeypatch.delenv("FOGHTTP_BENCHMARK_RESEARCH_MANIFEST", raising=False)
