from copy import deepcopy

import pytest

from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.streaming.finalization import StreamingMetadataMergeError, merged_streaming_metadata


SCALAR_FIELDS = ("measurement_scope", "streaming_metric_schema_version", "bytes_payload_policy")
SCOPE_FIELDS = ("throughput_scopes", "timing_scopes")


@pytest.mark.parametrize("children", [[], [{}], [{}, {}]])
def test_absent_streaming_contracts_remain_absent(children: list[JsonObject]) -> None:
    assert merged_streaming_metadata(children) == {}


def test_metadata_merge_preserves_contracts_and_ignores_unowned_fields() -> None:
    contract: JsonObject = {
        "measurement_scope": "shared-client-server-process-v1",
        "streaming_metric_schema_version": 2,
        "bytes_payload_policy": "byte-pattern-0-255-v1",
    }
    children = [{**contract, "unowned": "first"}, {**contract, "unowned": "second"}]

    assert merged_streaming_metadata(children) == contract


@pytest.mark.parametrize("key", SCALAR_FIELDS)
def test_scalar_disagreement_raises_typed_error(key: str) -> None:
    with pytest.raises(StreamingMetadataMergeError, match=f"^Isolated streaming children disagree on {key}$"):
        merged_streaming_metadata([{key: "first"}, {key: "second"}])


@pytest.mark.parametrize("key", SCALAR_FIELDS)
@pytest.mark.parametrize("missing_first", [False, True])
def test_missing_scalar_cannot_silently_change_contract(key: str, *, missing_first: bool) -> None:
    children: list[JsonObject] = [{key: "present"}, {}]
    if missing_first:
        children.reverse()

    with pytest.raises(StreamingMetadataMergeError, match=f"children disagree on {key}"):
        merged_streaming_metadata(children)


@pytest.mark.parametrize("key", SCALAR_FIELDS)
def test_explicit_null_scalar_remains_distinct_from_missing(key: str) -> None:
    assert merged_streaming_metadata([{key: None}, {key: None}]) == {key: None}

    with pytest.raises(StreamingMetadataMergeError, match=f"children disagree on {key}"):
        merged_streaming_metadata([{key: None}, {}])


@pytest.mark.parametrize("key", SCOPE_FIELDS)
def test_scope_union_is_sorted_and_deduplicated_without_mutation(key: str) -> None:
    children: list[JsonObject] = [{key: ["z", "a", "z"]}, {key: ["m", "a"]}, {key: []}]
    original = deepcopy(children)

    merged = merged_streaming_metadata(children)

    assert merged == {key: ["a", "m", "z"]}
    assert children == original
    assert merged[key] is not children[0][key]


@pytest.mark.parametrize("key", SCOPE_FIELDS)
def test_explicit_empty_scope_lists_remain_present(key: str) -> None:
    assert merged_streaming_metadata([{key: []}, {key: []}]) == {key: []}


@pytest.mark.parametrize("key", SCOPE_FIELDS)
@pytest.mark.parametrize("invalid", [None, "scope", ("scope",), {}, [1], ["scope", False]])
def test_malformed_scope_fields_raise_typed_error(key: str, invalid: object) -> None:
    with pytest.raises(
        StreamingMetadataMergeError,
        match=f"^Isolated streaming child field {key} must be a list of strings$",
    ):
        merged_streaming_metadata([{key: ["scope"]}, {key: invalid}])


@pytest.mark.parametrize("key", SCOPE_FIELDS)
@pytest.mark.parametrize("missing_first", [False, True])
def test_missing_scope_field_is_rejected_when_another_child_declares_it(key: str, *, missing_first: bool) -> None:
    children: list[JsonObject] = [{key: []}, {}]
    if missing_first:
        children.reverse()

    with pytest.raises(StreamingMetadataMergeError, match=f"child field {key} must be a list of strings"):
        merged_streaming_metadata(children)


def test_metadata_error_preserves_value_error_contract() -> None:
    assert issubclass(StreamingMetadataMergeError, ValueError)
