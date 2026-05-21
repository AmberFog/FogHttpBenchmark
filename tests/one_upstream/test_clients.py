from foghttp_benchmark.one_upstream.cases import FORM_BODY, all_headers, all_params, one_upstream_cases
from foghttp_benchmark.one_upstream.clients import inspect_payload_matches, request_kwargs


def test_request_kwargs_use_common_httpx_compatible_payloads() -> None:
    case = one_upstream_cases()["direct-post-form"]

    kwargs = request_kwargs(case, "http://127.0.0.1:8000")

    assert kwargs["url"] == "http://127.0.0.1:8000/v1/inspect"
    assert kwargs["headers"] == all_headers()
    assert kwargs["params"] == all_params()
    assert kwargs["data"] == FORM_BODY


def test_inspect_payload_matches_expected_get_contract() -> None:
    case = one_upstream_cases()["defaults-get"]
    payload = {
        "body_text": "",
        "headers": all_headers(),
        "method": "GET",
        "path": "/v1/inspect",
        "query_items": [list(item) for item in all_params()],
    }

    assert inspect_payload_matches(case, payload)


def test_inspect_payload_rejects_missing_default_header() -> None:
    case = one_upstream_cases()["defaults-get"]
    headers = all_headers()
    headers.pop("x-client-default")
    payload = {
        "body_text": "",
        "headers": headers,
        "method": "GET",
        "path": "/v1/inspect",
        "query_items": [list(item) for item in all_params()],
    }

    assert not inspect_payload_matches(case, payload)


def test_inspect_payload_matches_form_body() -> None:
    case = one_upstream_cases()["direct-post-form"]
    payload = {
        "body_text": "grant_type=client_credentials&scope=read&scope=write",
        "headers": all_headers(),
        "method": "POST",
        "path": "/v1/inspect",
        "query_items": [list(item) for item in all_params()],
    }

    assert inspect_payload_matches(case, payload)
