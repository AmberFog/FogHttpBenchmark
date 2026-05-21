__all__ = ("compressed_response_scenarios",)

from foghttp_benchmark.compressed_response.payloads import COMPRESSED_RESPONSE_BODIES
from foghttp_benchmark.models import Scenario


def compressed_response_scenarios() -> dict[str, Scenario]:
    return {
        "gzip-json-small": Scenario(
            name="gzip-json-small",
            method="GET",
            path="/compressed/gzip-json-small",
            expected_json_keys=("ok", "message", "items"),
            description="GET gzip-compressed small JSON and decode buffered content.",
        ),
        "gzip-64k": compressed_scenario("gzip-64k"),
        "deflate-64k": compressed_scenario("deflate-64k"),
        "br-64k": compressed_scenario("br-64k"),
        "gzip-high-ratio-1m": compressed_scenario("gzip-high-ratio-1m"),
        "multi-gzip-deflate-64k": compressed_scenario("multi-gzip-deflate-64k"),
    }


def compressed_scenario(name: str) -> Scenario:
    body = COMPRESSED_RESPONSE_BODIES[name]
    return Scenario(
        name=name,
        method="GET",
        path=f"/compressed/{name}",
        expected_content_length=len(body.decoded_body),
        description=f"GET {name} compressed body and verify decoded length.",
    )
