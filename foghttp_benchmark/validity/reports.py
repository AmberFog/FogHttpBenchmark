__all__ = ("metadata_with_validity",)

from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.validity.classification import classify_report_validity
from foghttp_benchmark.validity.serialization import validity_payload


def metadata_with_validity(metadata: JsonObject, aggregate_rows: list[JsonObject]) -> JsonObject:
    metadata = dict(metadata)
    suite = str(metadata.get("suite", "unknown"))
    metadata["validity"] = validity_payload(
        classify_report_validity(
            suite=suite,
            aggregate_rows=aggregate_rows,
            metadata=metadata,
        ),
    )
    return metadata
