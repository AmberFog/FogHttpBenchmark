from pathlib import Path

import pytest

from foghttp_benchmark.streaming import lifecycle_worker
from foghttp_benchmark.streaming.attribution_models import AttributionConfig
from foghttp_benchmark.streaming.lifecycle_models import LifecycleCase, LifecycleConfig


@pytest.mark.parametrize("name", ["HTTP_PROXY", "NO_PROXY", "http_proxy", "no_proxy"])
def test_proxy_environment_fails_before_client_creation_without_recording_values(
    name: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    contamination = "http://example.invalid/unrecorded-proxy-setting"
    monkeypatch.setenv(name, contamination)

    report = lifecycle_worker.run_lifecycle_worker(
        LifecycleCase(1, "foghttp", "async", "stream-1m", 1, 1),
        LifecycleConfig(attribution=AttributionConfig(), post_gc=False),
        server_url="http://127.0.0.1:1",
        control_dir=tmp_path,
        output=tmp_path / "client.json",
    )

    assert report["status"] == "failed"
    assert report["proxy_environment_presence"][name] is True
    assert "proxy variables" in report["errors"][0]["message"]
    assert "client_construction_ms" not in report
    assert contamination not in (tmp_path / "client.json").read_text()


def test_active_python_profiler_cannot_be_reported_as_control(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(lifecycle_worker.sys, "getprofile", object)

    report = lifecycle_worker.run_lifecycle_worker(
        LifecycleCase(1, "foghttp", "async", "stream-1m", 1, 1),
        LifecycleConfig(attribution=AttributionConfig(), post_gc=False),
        server_url="http://127.0.0.1:1",
        control_dir=tmp_path,
        output=tmp_path / "client.json",
    )

    assert report["status"] == "failed"
    assert "diagnostic" in report["errors"][0]["message"]
    assert "client_construction_ms" not in report
