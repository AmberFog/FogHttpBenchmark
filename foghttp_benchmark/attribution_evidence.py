__all__ = (
    "ATTRIBUTION_POLICY_VERSION",
    "ATTRIBUTION_SCHEMA_VERSION",
    "condition_fingerprint",
    "harness_fingerprint",
    "inspect_raw_evidence",
    "write_raw_sidecar",
)

import hashlib
import json
from pathlib import Path
from typing import cast

from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.profile_evidence import inspect_profile_evidence


MAX_SIDECAR_BYTES = 64 * 1024 * 1024
ATTRIBUTION_SCHEMA_VERSION = 3
ATTRIBUTION_POLICY_VERSION = "async-bytes-v2"
GIT_SHA_LENGTH = 40


def condition_fingerprint(conditions: JsonObject) -> str:
    encoded = json.dumps(conditions, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def harness_fingerprint(metadata: JsonObject) -> str | None:
    provenance = metadata.get("research_provenance")
    manifest = provenance.get("manifest") if isinstance(provenance, dict) else None
    harness = manifest.get("harness") if isinstance(manifest, dict) else None
    if not isinstance(harness, dict):
        return None
    sha, diff, files = harness.get("sha"), harness.get("diff_sha256"), harness.get("files_sha256")
    if (
        not hex_digest(sha, GIT_SHA_LENGTH)
        or not hex_digest(diff, hashlib.sha256().digest_size * 2)
        or not isinstance(files, dict)
        or not files
        or not all(
            isinstance(name, str) and name and hex_digest(value, hashlib.sha256().digest_size * 2)
            for name, value in files.items()
        )
    ):
        return None
    # Checkout paths and branch names do not alter the measured harness contents.
    return condition_fingerprint(
        {"sha": sha, "diff_sha256": diff, "files_sha256_sha256": condition_fingerprint(cast("JsonObject", files))},
    )


def hex_digest(value: object, length: int) -> bool:
    return (
        isinstance(value, str) and len(value) == length and all(character in "0123456789abcdef" for character in value)
    )


def write_raw_sidecar(directory: Path, name: str, payload: JsonObject, *, sequence: int) -> JsonObject:
    if Path(name).name != name:
        msg = "Raw evidence must be written directly inside the report raw directory"
        raise ValueError(msg)
    data = (json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    if len(data) > MAX_SIDECAR_BYTES:
        msg = "Raw evidence exceeds its bounded 64 MiB sidecar limit"
        raise ValueError(msg)
    checksum = hashlib.sha256(data).hexdigest()
    path = directory / "raw" / f"{Path(name).stem}-{checksum}.json"
    if path.resolve().parent != (directory / "raw").resolve() or not path.resolve().is_relative_to(directory.resolve()):
        msg = "Raw evidence directory resolves outside its declared location"
        raise ValueError(msg)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)
    return {
        "path": path.relative_to(directory).as_posix(),
        "sha256": checksum,
        "size_bytes": len(data),
        "kind": "per-repeat-stream-chunk-resource-evidence-v1",
        "sequence": sequence,
    }


def inspect_raw_evidence(metadata: JsonObject, directory: Path) -> JsonObject:
    references = metadata.get("raw_evidence")
    errors: list[str] = []
    if not isinstance(references, list) or not references:
        return {"status": "invalid", "errors": ["Raw evidence references are missing"], "checked": 0}
    root = directory.resolve()
    seen: set[str] = set()
    for index, item in enumerate(references):
        error = inspect_reference(item, index, root, seen)
        if error is not None:
            errors.append(error)
    return {"status": "invalid" if errors else "ok", "errors": errors, "checked": len(references)}


def inspect_reference(item: object, index: int, root: Path, seen: set[str]) -> str | None:
    if not isinstance(item, dict):
        return f"Raw evidence reference {index} is malformed"
    reference = cast("JsonObject", item)
    name = reference.get("path")
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        return f"Raw evidence reference {index} must have a relative path"
    path = (root / name).resolve()
    if not path.is_relative_to(root) or name in seen:
        return f"Raw evidence reference {index} escapes the report directory or is duplicated"
    seen.add(name)
    size = reference.get("size_bytes")
    if type(size) is not int or not 0 < size <= MAX_SIDECAR_BYTES:
        return f"Raw evidence reference {index} has an invalid size"
    return inspect_sidecar_file(path, reference)


def inspect_sidecar_file(path: Path, reference: JsonObject) -> str | None:
    name = reference["path"]
    try:
        if path.stat().st_size != reference["size_bytes"]:
            return f"Raw evidence size differs: {name}"
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != reference.get("sha256"):
            return f"Raw evidence checksum differs: {name}"
        payload = json.loads(data)
        if not isinstance(payload, dict) or payload.get("sequence") != reference.get("sequence"):
            return f"Raw evidence identity differs: {name}"
        result = payload.get("result")
        profile_errors = (
            inspect_profile_evidence(result, path.parent.parent)
            if isinstance(result, dict)
            else ["Raw result is missing"]
        )
        if profile_errors:
            return f"Profiler evidence failed: {name} ({'; '.join(profile_errors)})"
    except (OSError, ValueError) as exc:
        return f"Raw evidence is unavailable: {name} ({type(exc).__name__})"
    return None
