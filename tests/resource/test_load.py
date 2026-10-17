import asyncio
from collections import Counter
from io import StringIO
from unittest.mock import create_autospec

import pytest
from rich.console import Console

from foghttp_benchmark.clients.base import AsyncClientAdapter, SyncClientAdapter
from foghttp_benchmark.models import ResponseOutcome, Scenario
from foghttp_benchmark.progress import BenchmarkProgress
from foghttp_benchmark.resource.runner import run_case_load_with_progress


@pytest.mark.parametrize("adapter", [AsyncClientAdapter, SyncClientAdapter], ids=["async", "sync"])
@pytest.mark.parametrize("secondary_url", [None, "http://secondary.invalid/bytes"])
@pytest.mark.parametrize("with_progress", [False, True])
@pytest.mark.parametrize("collect", [False, True])
def test_resource_load_preserves_work_and_errors_across_dispatch_paths(
    adapter: type[AsyncClientAdapter] | type[SyncClientAdapter],
    secondary_url: str | None,
    *,
    with_progress: bool,
    collect: bool,
) -> None:
    primary_url = "http://primary.invalid/bytes"
    client = create_autospec(adapter, instance=True)
    client.request.side_effect = lambda _scenario, url: ResponseOutcome(200 if url == primary_url else 500)
    progress = BenchmarkProgress(
        enabled=with_progress,
        console=Console(file=StringIO(), force_terminal=False),
    )

    result = asyncio.run(
        run_case_load_with_progress(
            client,
            Scenario("resource-load", "GET", "/bytes"),
            primary_url,
            secondary_url,
            concurrency=2,
            requests=4,
            collect=collect,
            progress=progress,
            stage_name="Resource correctness load",
        ),
    )

    observed_urls = Counter(call.args[1] for call in client.request.call_args_list)
    expected_urls = {primary_url: 4} if secondary_url is None else {primary_url: 2, secondary_url: 2}
    assert observed_urls == expected_urls
    assert len(result.latencies_ms) == (4 if collect else 0)
    assert result.errors == (0 if secondary_url is None else 2)
    assert result.error_types == ({} if secondary_url is None else {"check_failed": 2})
