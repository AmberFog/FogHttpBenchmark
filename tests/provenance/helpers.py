__all__ = ("InstalledDistribution", "install_wheel", "make_wheel")

import base64
import csv
import hashlib
from importlib import metadata
import io
import json
from pathlib import Path
from zipfile import ZipFile


class InstalledDistribution(metadata.Distribution):
    def __init__(self, root: Path, dist_info: str) -> None:
        self.root = root
        self.dist_info = dist_info

    def read_text(self, filename: str) -> str | None:
        path = self.root / self.dist_info / filename
        return path.read_text() if path.exists() else None

    def locate_file(self, path: str | Path) -> Path:
        return self.root / path


def make_wheel(
    root: Path,
    *,
    name: str = "foghttp",
    natives: tuple[str, ...] = ("foghttp/_foghttp.abi3.so",),
    extra_files: dict[str, bytes] | None = None,
    corrupt_member: str | None = None,
) -> Path:
    version = "0.4.2" if name == "foghttp" else "0.1.0"
    package = name.replace("-", "_")
    dist_info = f"{package}-{version}.dist-info"
    files = {
        f"{package}/__init__.py": b'"""Installed wheel fixture."""\n',
        f"{dist_info}/METADATA": f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n".encode(),
        f"{dist_info}/WHEEL": b"Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: false\nTag: cp311-abi3-any\n",
        **dict.fromkeys(natives, b"native wheel payload"),
        **(extra_files or {}),
    }
    record = f"{dist_info}/RECORD"
    record_text = io.StringIO()
    writer = csv.writer(record_text, lineterminator="\n")
    for member, data in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")
        writer.writerow((member, "sha256=" + digest, str(len(data))))
    writer.writerow((record, "", ""))
    files[record] = record_text.getvalue().encode()
    if corrupt_member is not None:
        files[corrupt_member] = b"changed after RECORD generation"
    path = root / f"{package}-{version}-cp311-abi3-any.whl"
    with ZipFile(path, "w") as archive:
        for member, data in files.items():
            archive.writestr(member, data)
    return path


def install_wheel(path: Path, root: Path) -> InstalledDistribution:
    with ZipFile(path) as archive:
        for member in archive.namelist():
            target = root / member
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(member))
        dist_info = next(member.rsplit("/", 1)[0] for member in archive.namelist() if member.endswith("/RECORD"))
    distribution = InstalledDistribution(root, dist_info)
    direct_url = root / dist_info / "direct_url.json"
    direct_url.write_text(json.dumps({"url": path.as_uri(), "archive_info": {}}))
    return distribution
