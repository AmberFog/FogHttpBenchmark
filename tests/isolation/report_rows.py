from dataclasses import asdict, replace
import json

from foghttp_benchmark.models import JsonObject, RunResult
from foghttp_benchmark.reports import aggregate_results
from foghttp_benchmark.streaming.reports import aggregate_streaming_results
from tests.requests.factories import run_result
from tests.streaming.factories import streaming_result


def request_result(client: str, *, repeat: int = 1, ok_req_s: float = 100.0) -> RunResult:
    return replace(
        run_result(repeat=repeat, errors=0, warmup_errors=0, error_types={}, warmup_error_types={}),
        client=client,
        duration_s=100 / ok_req_s,
        requests_per_second=ok_req_s,
        ok_requests_per_second=ok_req_s,
    )


def request_aggregate(client: str, *, ok_req_s: float = 100.0) -> JsonObject:
    return json.loads(json.dumps(asdict(aggregate_results([request_result(client, ok_req_s=ok_req_s)])[0])))


def request_run(client: str, *, repeat: int = 1, ok_req_s: float = 100.0) -> JsonObject:
    return asdict(request_result(client, repeat=repeat, ok_req_s=ok_req_s))


def streaming_aggregate(scope: str) -> JsonObject:
    return json.loads(
        json.dumps(asdict(aggregate_streaming_results([replace(streaming_result(), timing_scope=scope)])[0])),
    )


def streaming_run(scope: str) -> JsonObject:
    return asdict(replace(streaming_result(), timing_scope=scope))
