from pathlib import Path

from tests.architecture.rules import boundary_violations


PACKAGE = Path(__file__).resolve().parents[2] / "foghttp_benchmark"


def test_selected_import_boundaries_on_actual_source_tree() -> None:
    violations = []
    for path in sorted(PACKAGE.rglob("*.py")):
        parts = path.relative_to(PACKAGE.parent).with_suffix("").parts
        is_package = parts[-1] == "__init__"
        module = ".".join(parts[:-1] if is_package else parts)
        violations.extend(boundary_violations(module, path.read_text(), is_package=is_package))

    assert violations == [], "\n".join(violations)
