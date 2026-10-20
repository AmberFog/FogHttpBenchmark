from pathlib import Path


REPORT_TIMESTAMP = "20261018-120000"
REPORT_NAMES = (f"{REPORT_TIMESTAMP}.json", "latest.json", f"{REPORT_TIMESTAMP}.md", "latest.md")


def existing_outputs(output_dir: Path, *, existing: bool) -> dict[str, bytes]:
    if not existing:
        return {}
    output_dir.mkdir(parents=True)
    contents = {name: f"previous report: {name}\n".encode() for name in REPORT_NAMES}
    for name, content in contents.items():
        (output_dir / name).write_bytes(content)
    return contents


def output_contents(output_dir: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in output_dir.iterdir()} if output_dir.exists() else {}
