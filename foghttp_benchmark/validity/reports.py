__all__ = ("metadata_with_validity",)

from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.provenance import package_sources, research_provenance_from_env
from foghttp_benchmark.report_schema.models import REPORT_SCHEMA_VERSION
from foghttp_benchmark.validity.classification import classify_report_validity
from foghttp_benchmark.validity.serialization import validity_payload


def metadata_with_validity(metadata: JsonObject, aggregate_rows: list[JsonObject]) -> JsonObject:
    metadata = dict(metadata)
    metadata["report_schema_version"] = REPORT_SCHEMA_VERSION
    provenance = research_provenance_from_env()
    if provenance is not None:
        metadata["research_provenance"] = provenance
        metadata["package_sources"] = package_sources(["foghttp"])
    suite = str(metadata.get("suite", "unknown"))
    metadata["validity"] = validity_payload(
        classify_report_validity(
            suite=suite,
            aggregate_rows=aggregate_rows,
            metadata=metadata,
        ),
    )
    return metadata
