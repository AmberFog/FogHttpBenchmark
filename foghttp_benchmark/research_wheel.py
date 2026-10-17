__all__ = ("file_sha256", "inspect_distribution_wheel", "inspect_wheel", "verify_installed_wheel")

import base64
import csv
from email.parser import BytesParser
import hashlib
from importlib import metadata
import io
import json
from pathlib import Path, PurePosixPath
from typing import cast
from urllib.parse import unquote, urlparse
from zipfile import ZipFile

from foghttp_benchmark.models import JsonObject


RECORD_COLUMNS = 3


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inspect_wheel(path: Path) -> JsonObject:
    return inspect_distribution_wheel(path, "foghttp")


def inspect_distribution_wheel(path: Path, name: str) -> JsonObject:
    with ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            msg = "Wheel contains duplicate entries"
            raise ValueError(msg)
        files = {item.filename: archive.read(item) for item in archive.infolist() if not item.is_dir()}
    for member in files:
        safe_member(member)
    records = [member for member in files if member.endswith(".dist-info/RECORD")]
    if len(records) != 1:
        msg = "Wheel must contain one RECORD"
        raise ValueError(msg)
    record = records[0]
    rows = {row[0]: row for row in csv.reader(io.StringIO(files[record].decode())) if row}
    for member, data in files.items():
        if member == record:
            continue
        row = rows.get(member, [])
        encoded = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")
        if len(row) != RECORD_COLUMNS or row[1] != "sha256=" + encoded or row[2] != str(len(data)):
            msg = f"Wheel RECORD mismatch: {member}"
            raise ValueError(msg)
    dist_info = record.rsplit("/", 1)[0]
    headers = BytesParser().parsebytes(files[dist_info + "/METADATA"])
    actual_name = str(headers.get("Name", "")).lower().replace("_", "-")
    if actual_name != name.lower().replace("_", "-"):
        msg = f"Wrong wheel distribution: {actual_name}"
        raise ValueError(msg)
    natives = [
        member for member in files if member.startswith("foghttp/_foghttp.") and member.endswith((".so", ".pyd"))
    ]
    if name == "foghttp" and len(natives) != 1:
        msg = "FogHTTP wheel must contain exactly one native module"
        raise ValueError(msg)
    native = natives[0] if natives else None
    hashes = {member: hashlib.sha256(data).hexdigest() for member, data in files.items() if member != record}
    return {
        "path": str(path.resolve()),
        "sha256": file_sha256(path),
        "version": str(headers.get("Version", "")),
        "native_member": native,
        "native_sha256": hashes[native] if native else None,
        "files_sha256": hashes,
    }


def safe_member(member: str) -> None:
    path = PurePosixPath(member)
    if path.is_absolute() or ".." in path.parts or "\\" in member:
        msg = f"Unsafe wheel member: {member}"
        raise ValueError(msg)


def verify_installed_wheel(wheel: JsonObject, name: str, prefix: Path) -> metadata.Distribution:
    path = Path(str(wheel["path"]))
    if inspect_distribution_wheel(path, name) != wheel:
        msg = f"Wheel identity changed: {name}"
        raise ValueError(msg)
    distribution = metadata.distribution(name)
    if distribution.version != wheel["version"]:
        msg = f"Wrong installed version: {name}"
        raise ValueError(msg)
    direct = json.loads(distribution.read_text("direct_url.json") or "{}")
    origin = urlparse(str(direct.get("url", "")))
    if "dir_info" in direct or origin.scheme != "file" or Path(unquote(origin.path)).resolve() != path.resolve():
        msg = f"Installation must originate from the recorded local wheel, without editable mode: {name}"
        raise ValueError(msg)
    hashes = wheel.get("files_sha256")
    if not isinstance(hashes, dict):
        msg = f"Missing wheel file hashes: {name}"
        raise TypeError(msg)
    records = {row[0]: row for row in csv.reader(io.StringIO(distribution.read_text("RECORD") or "")) if row}
    for member, expected in cast("JsonObject", hashes).items():
        safe_member(member)
        installed = Path(str(distribution.locate_file(member))).resolve()
        if not installed.is_relative_to(prefix.resolve()) or file_sha256(installed) != expected:
            msg = f"Installed file does not match wheel: {member}"
            raise ValueError(msg)
        row = records.get(member, [])
        encoded = base64.urlsafe_b64encode(bytes.fromhex(str(expected))).decode().rstrip("=")
        if len(row) != RECORD_COLUMNS or row[1] != "sha256=" + encoded or row[2] != str(installed.stat().st_size):
            msg = f"Installed RECORD differs from the wheel: {member}"
            raise ValueError(msg)
    return distribution
