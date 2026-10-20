__all__ = ("finalize_merged_report", "run_proxy_connect_suite", "select_clients")

from foghttp_benchmark.isolation.models import ClientIsolationSelection
from foghttp_benchmark.models import BenchmarkArgs, JsonObject
from foghttp_benchmark.progress import ProgressReporter, progress_status
from foghttp_benchmark.proxy_connect import (
    available_proxy_connect_clients,
    proxy_connect_cases,
    run_proxy_connect_benchmarks,
    write_proxy_connect_reports,
)
from foghttp_benchmark.proxy_connect.finalization import finalize_proxy_connect_rows
from foghttp_benchmark.proxy_connect.models import ProxyConnectEndpoints
from foghttp_benchmark.proxy_connect.proxy_server import benchmark_tls_server, http_proxy_server
from foghttp_benchmark.report_finalization import MergedSuiteReport
from foghttp_benchmark.server import benchmark_server
from foghttp_benchmark.suite_selection import isolation_selection, parse_csv, parse_int_csv
from foghttp_benchmark.validation import validate_proxy_connect_args


async def run_proxy_connect_suite(
    args: BenchmarkArgs,
    *,
    progress: ProgressReporter | None = None,
) -> None:
    progress_status(progress, "Building proxy CONNECT benchmark plan")
    requested_clients = parse_csv(args.clients)
    requested_modes = parse_csv(args.modes)
    clients, skipped = available_proxy_connect_clients(requested_clients, requested_modes)
    if not clients:
        msg = "proxy-connect suite requires foghttp, httpx, or httpxyz clients"
        raise ValueError(msg)
    case_map = proxy_connect_cases()
    requested_cases = parse_csv(args.scenarios)
    concurrency_levels = parse_int_csv(args.concurrency)
    validate_proxy_connect_args(
        args,
        requested_cases=requested_cases,
        case_map=case_map,
        concurrency_levels=concurrency_levels,
    )
    cases = [case_map[name] for name in requested_cases]
    progress_status(progress, "Starting local HTTP, HTTPS, and proxy benchmark servers")
    async with (
        benchmark_server() as http_base_url,
        benchmark_tls_server() as tls_endpoint,
        http_proxy_server() as proxy,
    ):
        endpoints = ProxyConnectEndpoints(
            http_base_url=http_base_url,
            https_base_url=tls_endpoint.base_url,
            proxy_url=proxy.url,
            ca_cert_path=tls_endpoint.ca_cert_path,
        )
        results = await run_proxy_connect_benchmarks(
            clients=clients,
            endpoints=endpoints,
            proxy_stats=proxy.stats,
            cases=cases,
            concurrency_levels=concurrency_levels,
            requests=args.requests,
            warmup=args.warmup,
            repeats=args.repeats,
            shuffle=not args.no_shuffle,
            seed=args.seed,
            progress=progress,
        )

    progress_status(progress, "Writing proxy CONNECT reports")
    write_proxy_connect_reports(results, skipped, args, proxy_url=proxy.url)


def select_clients(args: BenchmarkArgs) -> ClientIsolationSelection:
    clients, skipped = available_proxy_connect_clients(parse_csv(args.clients), parse_csv(args.modes))
    return isolation_selection(args, clients, skipped)


def finalize_merged_report(rows: list[JsonObject], _children_metadata: list[JsonObject]) -> MergedSuiteReport:
    return MergedSuiteReport(finalize_proxy_connect_rows(rows), {})
