from foghttp_benchmark.constants import PROXY_CONNECT_SUITE, RESPONSE_STREAMING_SUITE
from foghttp_benchmark.models import BenchmarkArgs
from foghttp_benchmark.proxy_connect.reports import write_proxy_connect_reports
from foghttp_benchmark.reports import write_reports
from foghttp_benchmark.streaming.reports import write_streaming_reports


def write_empty_child_report(args: BenchmarkArgs) -> None:
    if args.suite == RESPONSE_STREAMING_SUITE:
        write_streaming_reports([], {}, args)
    elif args.suite == PROXY_CONNECT_SUITE:
        write_proxy_connect_reports([], {}, args, proxy_url="http://127.0.0.1:1")
    else:
        write_reports([], {}, args)
