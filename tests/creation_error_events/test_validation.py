import re

import pytest

from foghttp_benchmark.report_schema.ordinary import validate_ordinary_rows
from tests.report_schema.ordinary_fixtures import ordinary_aggregate, ordinary_run


@pytest.mark.parametrize("collection", ("aggregate", "runs"))
@pytest.mark.parametrize(
    ("scenario", "run_limit"),
    (
        ("create-close", 2),
        ("create-first-request", 6),
        ("reused-request", 4),
        ("many-clients-open-close", 3),
        ("unknown-legacy-scenario", 2),
    ),
)
def test_creation_errors_exceeding_the_scenario_event_limit_are_rejected(
    collection: str,
    scenario: str,
    run_limit: int,
) -> None:
    row = ordinary_aggregate("client-creation") if collection == "aggregate" else ordinary_run("client-creation")
    row.update(scenario=scenario, iterations=2, client_count=2)
    field = "errors_total" if collection == "aggregate" else "errors"
    row[field] = run_limit * (2 if collection == "aggregate" else 1) + 1
    row["error_types"] = {"RuntimeError": row[field]}

    with pytest.raises(ValueError, match=re.escape(f"{collection}[0].{field}")):
        validate_ordinary_rows(
            "client-creation",
            [row] if collection == "aggregate" else [],
            [row] if collection == "runs" else [],
        )


@pytest.mark.parametrize("collection", ("aggregate", "runs"))
def test_many_clients_cannot_expand_its_error_limit_with_a_contradictory_client_count(collection: str) -> None:
    row = ordinary_aggregate("client-creation") if collection == "aggregate" else ordinary_run("client-creation")
    row.update(scenario="many-clients-open-close", iterations=1, client_count=100)

    with pytest.raises(ValueError, match=re.escape(f"{collection}[0].iterations must equal client_count")):
        validate_ordinary_rows(
            "client-creation",
            [row] if collection == "aggregate" else [],
            [row] if collection == "runs" else [],
        )


@pytest.mark.parametrize("collection", ("aggregate", "runs"))
@pytest.mark.parametrize("value", (True, -1, 0.5, "2", None))
def test_creation_event_counts_still_require_nonnegative_integers(collection: str, value: object) -> None:
    row = ordinary_aggregate("client-creation") if collection == "aggregate" else ordinary_run("client-creation")
    row["scenario"] = "create-first-request"
    field = "errors_total" if collection == "aggregate" else "errors"
    row[field] = value

    with pytest.raises((TypeError, ValueError), match=re.escape(f"{collection}[0].{field}")):
        validate_ordinary_rows(
            "client-creation",
            [row] if collection == "aggregate" else [],
            [row] if collection == "runs" else [],
        )


@pytest.mark.parametrize("collection", ("aggregate", "runs"))
@pytest.mark.parametrize("errors", ({"RuntimeError": 1}, {"RuntimeError": True}, {"RuntimeError": -1}, []))
def test_creation_event_maps_must_be_strict_and_sum_to_total(collection: str, errors: object) -> None:
    row = ordinary_aggregate("client-creation") if collection == "aggregate" else ordinary_run("client-creation")
    row.update(scenario="create-first-request", error_types=errors)

    with pytest.raises((TypeError, ValueError), match=re.escape(f"{collection}[0].error_types")):
        validate_ordinary_rows(
            "client-creation",
            [row] if collection == "aggregate" else [],
            [row] if collection == "runs" else [],
        )


@pytest.mark.parametrize("suite", ("request-builder", "requests", "compressed-response"))
@pytest.mark.parametrize("collection", ("aggregate", "runs"))
def test_operation_and_request_failure_counts_retain_their_original_bound(suite: str, collection: str) -> None:
    row = ordinary_aggregate(suite) if collection == "aggregate" else ordinary_run(suite)
    field = "errors_total" if collection == "aggregate" else "errors"
    row[field] = 9 if collection == "aggregate" else 5
    error_field = "ok_requests" if collection == "runs" and suite != "request-builder" else field

    with pytest.raises(ValueError, match=re.escape(f"{collection}[0].{error_field}")):
        validate_ordinary_rows(suite, [row] if collection == "aggregate" else [], [row] if collection == "runs" else [])
