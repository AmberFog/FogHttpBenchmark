__all__ = (
    "ASYNC_MODE",
    "BENCHMARK_SEED",
    "CLIENT_CREATION_SUITE",
    "COMPRESSED_RESPONSE_SUITE",
    "DEFAULT_CLIENTS",
    "DEFAULT_CLIENT_COUNTS",
    "DEFAULT_COMPRESSED_RESPONSE_SCENARIOS",
    "DEFAULT_CONCURRENCY",
    "DEFAULT_CREATION_ITERATIONS",
    "DEFAULT_MAX_REDIRECTS",
    "DEFAULT_MODES",
    "DEFAULT_ONE_UPSTREAM_SCENARIOS",
    "DEFAULT_REPEATS",
    "DEFAULT_REQUESTS",
    "DEFAULT_REQUEST_BUILDER_SCENARIOS",
    "DEFAULT_RESOURCE_SCENARIOS",
    "DEFAULT_SCENARIOS",
    "DEFAULT_WARMUP",
    "MAX_SPLIT_ONCE",
    "MIN_VARIATION_SAMPLES",
    "ONE_UPSTREAM_SUITE",
    "REQUESTS_SUITE",
    "REQUEST_BUILDER_SUITE",
    "RESOURCE_BACKPRESSURE_SUITE",
    "RESULTS_DIR",
    "ROOT",
    "SYNC_MODE",
)

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "results"

ASYNC_MODE = "async"
SYNC_MODE = "sync"

DEFAULT_CLIENTS = "foghttp,httpx,aiohttp,zapros"
DEFAULT_MODES = ASYNC_MODE
DEFAULT_CONCURRENCY = "1,10,50,100"
DEFAULT_REQUESTS = 2000
DEFAULT_WARMUP = 200
DEFAULT_REPEATS = 3
DEFAULT_MAX_REDIRECTS = 20
DEFAULT_CREATION_ITERATIONS = 100
DEFAULT_CLIENT_COUNTS = "1,10,50"
DEFAULT_SCENARIOS = (
    "json-small,"
    "json-decode-small,"
    "bytes-64k,"
    "post-json-echo,"
    "post-echo-64k,"
    "redirect-get-302,"
    "redirect-head-302,"
    "redirect-post-303,"
    "redirect-post-307,"
    "delay-20ms,"
    "pool-contention-20ms"
)
DEFAULT_RESOURCE_SCENARIOS = (
    "active-limit-serial,"
    "pool-timeout-recovery,"
    "pending-queue-full,"
    "per-origin-isolation,"
    "response-body-limit,"
    "aggregate-buffered-budget"
)
DEFAULT_COMPRESSED_RESPONSE_SCENARIOS = (
    "gzip-json-small,gzip-64k,deflate-64k,br-64k,gzip-high-ratio-1m,multi-gzip-deflate-64k"
)
DEFAULT_ONE_UPSTREAM_SCENARIOS = (
    "direct-get,"
    "base-url-get,"
    "defaults-get,"
    "prepared-get,"
    "direct-post-json,"
    "defaults-post-json,"
    "direct-post-form,"
    "defaults-post-form"
)
DEFAULT_REQUEST_BUILDER_SCENARIOS = (
    "absolute-url,"
    "base-url,"
    "default-headers,"
    "default-params,"
    "repeated-params,"
    "raw-query,"
    "many-query-params,"
    "json-body,"
    "bytes-body,"
    "send-prepared-get"
)

REQUESTS_SUITE = "requests"
CLIENT_CREATION_SUITE = "client-creation"
RESOURCE_BACKPRESSURE_SUITE = "resource-backpressure"
ONE_UPSTREAM_SUITE = "one-upstream"
REQUEST_BUILDER_SUITE = "request-builder"
COMPRESSED_RESPONSE_SUITE = "compressed-response"

BENCHMARK_SEED = 20260507
MIN_VARIATION_SAMPLES = 2
MAX_SPLIT_ONCE = 1
