import asyncio
import ssl

import httpx

from foghttp_benchmark.proxy_connect.proxy_server import benchmark_tls_server, http_proxy_server
from foghttp_benchmark.server import benchmark_server


HTTP_OK = 200


def test_proxy_server_routes_http_and_https_connect() -> None:
    asyncio.run(assert_proxy_routes_http_and_https_connect())


async def assert_proxy_routes_http_and_https_connect() -> None:
    async with (
        benchmark_server() as http_base_url,
        benchmark_tls_server() as tls_endpoint,
        http_proxy_server() as proxy,
    ):
        http_response, https_response = await fetch_through_proxy(
            http_base_url=http_base_url,
            https_base_url=tls_endpoint.base_url,
            proxy_url=proxy.url,
            ca_cert_path=tls_endpoint.ca_cert_path,
        )

    assert http_response.status_code == HTTP_OK
    assert http_response.json()["ok"]
    assert https_response.status_code == HTTP_OK
    assert https_response.json()["ok"]
    assert proxy.stats.http_requests == 1
    assert proxy.stats.connect_requests == 1


async def fetch_through_proxy(
    *,
    http_base_url: str,
    https_base_url: str,
    proxy_url: str,
    ca_cert_path: str,
) -> tuple[httpx.Response, httpx.Response]:
    tls_context = ssl.create_default_context(cafile=ca_cert_path)
    async with httpx.AsyncClient(proxy=proxy_url, verify=tls_context, trust_env=False) as client:
        http_response = await client.get(http_base_url + "/json-small")
        https_response = await client.get(https_base_url + "/json-small")
    return http_response, https_response
