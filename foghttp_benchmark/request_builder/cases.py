__all__ = (
    "BYTES_BODY",
    "DEFAULT_HEADERS",
    "DEFAULT_PARAMS",
    "JSON_BODY",
    "MANY_PARAMS",
    "RAW_QUERY",
    "REPEATED_PARAMS",
    "REQUEST_HEADERS",
    "REQUEST_PARAMS",
    "RequestBuilderCase",
    "request_builder_cases",
)

from foghttp_benchmark.request_builder.models import RequestBuilderCase


DEFAULT_HEADERS = {
    "accept": "application/json",
    "x-client-default": "foghttp-benchmark",
}
REQUEST_HEADERS = {
    "x-request-case": "request-builder",
}
DEFAULT_PARAMS = (
    ("api-version", "1"),
    ("locale", "en-US"),
    ("tenant", "bench"),
)
REQUEST_PARAMS = (
    ("limit", "10"),
    ("page", "2"),
)
REPEATED_PARAMS = (
    ("tag", "rust"),
    ("tag", "python"),
    ("tag", "http"),
)
RAW_QUERY = "limit=10&page=2&tag=rust&tag=python&feature=builder"
MANY_PARAMS = tuple((f"item{index}", str(index)) for index in range(50))
JSON_BODY = {
    "name": "Ada Lovelace",
    "role": "admin",
    "active": True,
}
BYTES_BODY = b"x" * 65_536


def request_builder_cases() -> dict[str, RequestBuilderCase]:
    return {
        "absolute-url": RequestBuilderCase(
            name="absolute-url",
            group="url",
            kind="build",
            profile="direct",
            method="GET",
            path="v1/inspect",
            uses_base_url=False,
            description="Build a GET request from an absolute URL without client defaults.",
        ),
        "base-url": RequestBuilderCase(
            name="base-url",
            group="url",
            kind="build",
            profile="base-url",
            method="GET",
            path="v1/inspect",
            uses_base_url=True,
            description="Build a GET request through client base_url and a relative path.",
        ),
        "default-headers": RequestBuilderCase(
            name="default-headers",
            group="headers",
            kind="build",
            profile="defaults",
            method="GET",
            path="v1/inspect",
            uses_base_url=True,
            default_headers=True,
            request_headers=True,
            description="Merge client-level headers with per-request headers.",
        ),
        "default-params": RequestBuilderCase(
            name="default-params",
            group="query",
            kind="build",
            profile="defaults",
            method="GET",
            path="v1/inspect",
            uses_base_url=True,
            default_params=True,
            params_kind="scalar",
            description="Merge client-level query params with per-request scalar params.",
        ),
        "repeated-params": RequestBuilderCase(
            name="repeated-params",
            group="query",
            kind="build",
            profile="repeated",
            method="GET",
            path="v1/inspect",
            uses_base_url=True,
            default_params=True,
            params_kind="repeated",
            description="Build a request with repeated query parameters.",
        ),
        "raw-query": RequestBuilderCase(
            name="raw-query",
            group="query",
            kind="build",
            profile="raw",
            method="GET",
            path="v1/inspect",
            uses_base_url=True,
            params_kind="raw",
            description="Build a request from a raw query string params payload.",
        ),
        "many-query-params": RequestBuilderCase(
            name="many-query-params",
            group="query",
            kind="build",
            profile="many",
            method="GET",
            path="v1/inspect",
            uses_base_url=True,
            default_params=True,
            params_kind="many",
            description="Build a request with 50 per-request query parameters.",
        ),
        "json-body": RequestBuilderCase(
            name="json-body",
            group="body",
            kind="build",
            profile="json",
            method="POST",
            path="v1/inspect",
            uses_base_url=True,
            body_kind="json",
            description="Build a POST request with JSON body encoding.",
        ),
        "bytes-body": RequestBuilderCase(
            name="bytes-body",
            group="body",
            kind="build",
            profile="bytes",
            method="POST",
            path="v1/inspect",
            uses_base_url=True,
            body_kind="bytes",
            description="Build a POST request with a 64 KiB bytes body.",
        ),
        "send-prepared-get": RequestBuilderCase(
            name="send-prepared-get",
            group="send",
            kind="send-prepared",
            profile="prepared",
            method="GET",
            path="json-small",
            uses_base_url=True,
            default_headers=True,
            default_params=True,
            params_kind="scalar",
            description="Build and send a prepared GET request through a reused client.",
        ),
    }
