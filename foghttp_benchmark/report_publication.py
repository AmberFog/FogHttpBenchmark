__all__ = ("publish_report",)

import json
from pathlib import Path


def publish_report(
    output_dir: Path,
    identifier: str,
    payload: dict[str, object],
    markdown: str,
) -> None:
    """Publish a prepared report sequentially; errors propagate without rollback."""
    output_dir.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    (output_dir / f"{identifier}.json").write_text(json_text)
    (output_dir / "latest.json").write_text(json_text)
    (output_dir / f"{identifier}.md").write_text(markdown)
    (output_dir / "latest.md").write_text(markdown)
