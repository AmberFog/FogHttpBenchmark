import os

from pytest import MonkeyPatch

from foghttp_benchmark.proxy_connect.cases import proxy_connect_cases
from foghttp_benchmark.proxy_connect.models import ProxyStatsDelta
from foghttp_benchmark.proxy_connect.runner import proxy_environment, proxy_usage_error


def test_proxy_usage_error_rejects_direct_proxy_activity() -> None:
    error = proxy_usage_error(
        case=proxy_connect_cases()["direct-http"],
        requests=10,
        measured_proxy=ProxyStatsDelta(0, 0, 0, 0, 0),
        total_proxy=ProxyStatsDelta(1, 0, 0, 0, 0),
    )

    assert error == "unexpected_proxy_activity"


def test_proxy_usage_error_rejects_http_proxy_bypass() -> None:
    error = proxy_usage_error(
        case=proxy_connect_cases()["proxy-http"],
        requests=10,
        measured_proxy=ProxyStatsDelta(9, 0, 0, 0, 0),
        total_proxy=ProxyStatsDelta(10, 0, 0, 0, 0),
    )

    assert error == "proxy_http_bypass"


def test_proxy_usage_error_accepts_reused_connect_from_warmup() -> None:
    error = proxy_usage_error(
        case=proxy_connect_cases()["proxy-connect"],
        requests=10,
        measured_proxy=ProxyStatsDelta(0, 0, 0, 100, 200),
        total_proxy=ProxyStatsDelta(0, 1, 0, 300, 400),
    )

    assert error is None


def test_proxy_environment_restores_proxy_variables(monkeypatch: MonkeyPatch) -> None:
    proxy_url = "http://127.0.0.1:8080"
    monkeypatch.setenv("HTTP_PROXY", "http://existing-http-proxy.local")
    monkeypatch.setenv("HTTPS_PROXY", "http://existing-https-proxy.local")
    monkeypatch.setenv("ALL_PROXY", "http://existing-all-proxy.local")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")

    with proxy_environment(proxy_connect_cases()["trust-env-http"], proxy_url):
        assert os.environ["HTTP_PROXY"] == proxy_url
        assert os.environ["HTTPS_PROXY"] == proxy_url
        assert "ALL_PROXY" not in os.environ
        assert "NO_PROXY" not in os.environ

    assert os.environ["HTTP_PROXY"] == "http://existing-http-proxy.local"
    assert os.environ["HTTPS_PROXY"] == "http://existing-https-proxy.local"
    assert os.environ["ALL_PROXY"] == "http://existing-all-proxy.local"
    assert os.environ["NO_PROXY"] == "localhost,127.0.0.1"
