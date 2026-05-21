__all__ = (
    "DEFAULT_HEADERS",
    "DEFAULT_PARAMS",
    "FORM_BODY",
    "JSON_BODY",
    "REQUEST_HEADERS",
    "REQUEST_PARAMS",
    "OneUpstreamCase",
    "all_headers",
    "all_params",
    "one_upstream_cases",
)

from foghttp_benchmark.one_upstream.models import OneUpstreamCase, query_items


DEFAULT_HEADERS = {
    "accept": "application/json",
    "x-client-default": "foghttp-benchmark",
}
REQUEST_HEADERS = {
    "x-request-case": "one-upstream",
}
DEFAULT_PARAMS = query_items(
    (
        ("api-version", "1"),
        ("locale", "en-US"),
        ("tenant", "bench"),
    ),
)
REQUEST_PARAMS = query_items(
    (
        ("debug", "1"),
        ("limit", "10"),
        ("page", "2"),
    ),
)
JSON_BODY = {
    "name": "Ada Lovelace",
    "role": "admin",
}
FORM_BODY = {
    "grant_type": "client_credentials",
    "scope": ["read", "write"],
}


def one_upstream_cases() -> dict[str, OneUpstreamCase]:
    return {
        "direct-get": OneUpstreamCase(
            name="direct-get",
            group="get",
            profile="direct",
            method="GET",
            description="Absolute URL with all headers and params passed per request.",
        ),
        "base-url-get": OneUpstreamCase(
            name="base-url-get",
            group="get",
            profile="base-url",
            method="GET",
            description="Client base_url with headers and params still passed per request.",
        ),
        "defaults-get": OneUpstreamCase(
            name="defaults-get",
            group="get",
            profile="defaults",
            method="GET",
            description="Client base_url, default headers, default params, and per-request params.",
        ),
        "prepared-get": OneUpstreamCase(
            name="prepared-get",
            group="get",
            profile="prepared",
            method="GET",
            description="Build prepared request through client defaults and send it.",
        ),
        "direct-post-json": OneUpstreamCase(
            name="direct-post-json",
            group="post-json",
            profile="direct",
            method="POST",
            body_kind="json",
            description="Absolute URL POST JSON with all defaults passed per request.",
        ),
        "defaults-post-json": OneUpstreamCase(
            name="defaults-post-json",
            group="post-json",
            profile="defaults",
            method="POST",
            body_kind="json",
            description="POST JSON through client base_url, default headers, and default params.",
        ),
        "direct-post-form": OneUpstreamCase(
            name="direct-post-form",
            group="post-form",
            profile="direct",
            method="POST",
            body_kind="form",
            description="Absolute URL form-urlencoded POST with all defaults passed per request.",
        ),
        "defaults-post-form": OneUpstreamCase(
            name="defaults-post-form",
            group="post-form",
            profile="defaults",
            method="POST",
            body_kind="form",
            description="Form-urlencoded POST through client base_url, default headers, and default params.",
        ),
    }


def all_headers() -> dict[str, str]:
    return {**DEFAULT_HEADERS, **REQUEST_HEADERS}


def all_params() -> tuple[tuple[str, str], ...]:
    return (*DEFAULT_PARAMS, *REQUEST_PARAMS)
