from foghttp_benchmark.request_builder.cases import DEFAULT_PARAMS, MANY_PARAMS, REQUEST_PARAMS, request_builder_cases
from foghttp_benchmark.request_builder.clients import (
    client_config_for_case,
    request_kwargs,
    request_matches_case,
)


class FakeRequest:
    def __init__(self, *, method: str, url: str, content: bytes = b"") -> None:
        self.method = method
        self.url = url
        self.content = content
        self.headers: dict[str, str] = {}


def test_request_kwargs_use_relative_url_for_base_url_cases() -> None:
    case = request_builder_cases()["default-params"]

    kwargs = request_kwargs(case, "http://127.0.0.1:8000")

    assert kwargs["url"] == "v1/inspect"
    assert kwargs["params"] == REQUEST_PARAMS


def test_client_config_enables_defaults_only_for_matching_case_parts() -> None:
    case = request_builder_cases()["default-headers"]

    config = client_config_for_case(case, base_url="http://127.0.0.1:8000")

    assert config.base_url == "http://127.0.0.1:8000/"
    assert config.headers is not None
    assert config.params is None


def test_many_query_case_validates_all_expected_params() -> None:
    case = request_builder_cases()["many-query-params"]
    query = "&".join(f"{key}={value}" for key, value in (*DEFAULT_PARAMS, *MANY_PARAMS))
    request = FakeRequest(method="GET", url=f"http://127.0.0.1:1/v1/inspect?{query}")

    assert request_matches_case(case, request)


def test_json_body_case_validates_encoded_content() -> None:
    case = request_builder_cases()["json-body"]
    request = FakeRequest(
        method="POST",
        url="http://127.0.0.1:1/v1/inspect",
        content=b'{"name":"Ada Lovelace","role":"admin"}',
    )

    assert request_matches_case(case, request)
