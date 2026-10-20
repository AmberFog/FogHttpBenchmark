__all__ = ("StreamingMetadataMergeError", "merged_streaming_metadata")

from foghttp_benchmark.models import JsonObject


class StreamingMetadataMergeError(ValueError):
    """Child streaming metadata cannot share a merged report contract."""


def merged_streaming_metadata(children: list[JsonObject]) -> JsonObject:
    """Merge validated child metadata without changing its streaming contracts."""
    merged: JsonObject = {}
    for key in ("measurement_scope", "streaming_metric_schema_version", "bytes_payload_policy"):
        values = [child.get(key) for child in children]
        if any(key in child for child in children):
            if any(value != values[0] for value in values) or any(key not in child for child in children):
                msg = f"Isolated streaming children disagree on {key}"
                raise StreamingMetadataMergeError(msg)
            merged[key] = values[0]
    for key in ("throughput_scopes", "timing_scopes"):
        if not any(key in child for child in children):
            continue
        scopes: set[str] = set()
        for child in children:
            value = child.get(key)
            if not isinstance(value, list) or any(not isinstance(scope, str) for scope in value):
                msg = f"Isolated streaming child field {key} must be a list of strings"
                raise StreamingMetadataMergeError(msg)
            scopes.update(str(scope) for scope in value)
        merged[key] = sorted(scopes)
    return merged
