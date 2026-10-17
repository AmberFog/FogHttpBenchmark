__all__ = ("main",)

import argparse
import asyncio
import json
from pathlib import Path
import sys
from typing import Any

from foghttp_benchmark.provenance import verify_research_manifest
from foghttp_benchmark.research_build import prepare_research_environment
from foghttp_benchmark.research_smoke import run_installation_smoke


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare or verify the pinned FogHTTP 0.4.2 research installation.")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="Build release wheels and install a fresh research environment.")
    prepare.add_argument("--output-dir", required=True, type=Path)
    prepare.add_argument("--python", default=Path(sys.executable), type=Path)
    verify = commands.add_parser("verify", help="Verify installed wheel provenance; does not run measurements.")
    verify.add_argument("--manifest", required=True, type=Path)
    verify.add_argument("--check-remote", action="store_true")
    smoke = commands.add_parser(
        "smoke",
        help="Verify complete local HTTP/1.1 streaming without performance measurements.",
    )
    smoke.add_argument("--manifest", required=True, type=Path)
    arguments = parser.parse_args()
    result: dict[str, Any]
    if arguments.command == "prepare":
        result = {"manifest": str(prepare_research_environment(arguments.output_dir, arguments.python, Path.cwd()))}
    else:
        result = verify_research_manifest(arguments.manifest, check_remote=getattr(arguments, "check_remote", False))
        if arguments.command == "smoke":
            result["smoke"] = asyncio.run(run_installation_smoke())
            verify_research_manifest(arguments.manifest)
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
