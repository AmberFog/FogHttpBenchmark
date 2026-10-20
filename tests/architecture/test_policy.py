import pytest

from tests.architecture.imports import ImportReference, import_references
from tests.architecture.rules import boundary_violations


@pytest.mark.parametrize(
    ("module", "source"),
    [
        ("foghttp_benchmark.statistics", "import typer"),
        ("foghttp_benchmark.rendering", "from click import Command"),
        ("foghttp_benchmark.report_publication", "import argparse as cli"),
    ],
)
def test_shared_modules_reject_cli_framework_dependencies(module: str, source: str) -> None:
    assert boundary_violations(module, source)


@pytest.mark.parametrize(
    ("module", "source", "is_package", "expected"),
    [
        pytest.param(
            "foghttp_benchmark.application.execution",
            "import foghttp_benchmark.cli as commands\n"
            "def invoke():\n"
            "    from foghttp_benchmark import _child as child\n",
            False,
            [
                ImportReference("foghttp_benchmark.cli", 1, type_only=False),
                ImportReference("foghttp_benchmark._child", 3, type_only=False),
            ],
            id="direct-alias-and-local-from-root",
        ),
        pytest.param(
            "foghttp_benchmark.streaming.consume",
            "from .. import reports as writer\nfrom .models import StreamingResult\n",
            False,
            [
                ImportReference("foghttp_benchmark.reports", 1, type_only=False),
                ImportReference("foghttp_benchmark.streaming.models.StreamingResult", 2, type_only=False),
            ],
            id="relative-imports-use-owner-package",
        ),
        pytest.param(
            "foghttp_benchmark.streaming",
            "from . import models\nfrom .. import constants\n",
            True,
            [
                ImportReference("foghttp_benchmark.streaming.models", 1, type_only=False),
                ImportReference("foghttp_benchmark.constants", 2, type_only=False),
            ],
            id="package-initializer-relative-imports",
        ),
        pytest.param(
            "foghttp_benchmark.rendering",
            "import typing as t\n"
            "from typing import TYPE_CHECKING as types_only\n"
            "if t.TYPE_CHECKING:\n"
            "    from foghttp_benchmark import models\n"
            "else:\n"
            "    import foghttp_benchmark.cli\n"
            "if types_only:\n"
            "    import foghttp_benchmark.compare.models\n",
            False,
            [
                ImportReference("typing", 1, type_only=False),
                ImportReference("typing.TYPE_CHECKING", 2, type_only=False),
                ImportReference("foghttp_benchmark.models", 4, type_only=True),
                ImportReference("foghttp_benchmark.cli", 6, type_only=False),
                ImportReference("foghttp_benchmark.compare.models", 8, type_only=True),
            ],
            id="typing-aliases-and-runtime-else-branch",
        ),
    ],
)
def test_import_references_preserve_targets_locations_and_type_guards(
    module: str,
    source: str,
    *,
    is_package: bool,
    expected: list[ImportReference],
) -> None:
    assert import_references(module, source, is_package=is_package) == expected


@pytest.mark.parametrize(
    ("module", "source", "forbidden"),
    [
        pytest.param(
            "foghttp_benchmark.statistics",
            "from foghttp_benchmark.reports import aggregate_results",
            True,
            id="statistics-cannot-depend-on-request-writer",
        ),
        pytest.param(
            "foghttp_benchmark.rendering",
            "from foghttp_benchmark.models import BenchmarkArgs",
            True,
            id="rendering-model-imports-must-be-type-only",
        ),
        pytest.param(
            "foghttp_benchmark.rendering",
            "from typing import TYPE_CHECKING as tc\n"
            "if tc:\n"
            "    from foghttp_benchmark.reports import aggregate_results",
            True,
            id="type-guard-does-not-authorize-renderer-to-import-writer",
        ),
        pytest.param(
            "foghttp_benchmark.report_publication",
            "from foghttp_benchmark import models",
            True,
            id="publisher-cannot-import-project-models",
        ),
        pytest.param(
            "foghttp_benchmark.application.execution",
            "import foghttp_benchmark.cli as commands",
            True,
            id="application-cannot-import-cli-alias",
        ),
        pytest.param(
            "foghttp_benchmark.application.composition",
            "from typer import Typer",
            True,
            id="application-cannot-import-typer-symbol",
        ),
        pytest.param(
            "foghttp_benchmark.application.execution",
            "def execute():\n    import argparse",
            True,
            id="local-import-cannot-hide-cli-framework",
        ),
        pytest.param(
            "foghttp_benchmark.application.execution",
            "import typing as t\nif t.TYPE_CHECKING:\n    import click.core",
            True,
            id="type-guard-cannot-hide-cli-framework",
        ),
        pytest.param(
            "foghttp_benchmark.streaming.suite",
            "def run():\n    from foghttp_benchmark.application import composition",
            True,
            id="suite-cannot-import-composition-through-function",
        ),
        pytest.param(
            "foghttp_benchmark.request_suite",
            "from foghttp_benchmark import _child",
            True,
            id="request-suite-cannot-import-child-entrypoint",
        ),
        pytest.param(
            "foghttp_benchmark.streaming.lifecycle",
            "from .. import cli",
            True,
            id="lifecycle-orchestration-cannot-import-cli-relatively",
        ),
        pytest.param(
            "foghttp_benchmark.isolation.reports",
            "from ..streaming.finalization import merged_streaming_metadata",
            True,
            id="isolation-cannot-select-concrete-finalizer",
        ),
        pytest.param(
            "foghttp_benchmark.isolation.planning",
            "from foghttp_benchmark.resource import suite",
            True,
            id="isolation-cannot-import-concrete-suite",
        ),
        pytest.param(
            "foghttp_benchmark.isolation.execution",
            "from foghttp_benchmark.application.execution import execute",
            True,
            id="isolation-cannot-import-application",
        ),
        pytest.param(
            "foghttp_benchmark.runner",
            "def run():\n    import foghttp_benchmark.reports as reports",
            True,
            id="measurement-cannot-import-writer-locally",
        ),
        pytest.param(
            "foghttp_benchmark.creation.measurement",
            "from foghttp_benchmark import rendering",
            True,
            id="measurement-cannot-import-rendering",
        ),
        pytest.param(
            "foghttp_benchmark.streaming.lifecycle_worker",
            "from ..report_publication import publish_report",
            True,
            id="streaming-worker-cannot-publish-reports",
        ),
        pytest.param(
            "foghttp_benchmark.compare.analysis",
            "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from .. import cli",
            True,
            id="comparison-analysis-cannot-import-cli-for-types",
        ),
        pytest.param(
            "foghttp_benchmark.report_schema.decoding",
            "from ..streaming import lifecycle_reports",
            True,
            id="schema-cannot-import-streaming-writer",
        ),
        pytest.param(
            "foghttp_benchmark.validity.generic",
            "import foghttp_benchmark.rendering",
            True,
            id="validity-cannot-import-rendering",
        ),
        pytest.param(
            "foghttp_benchmark.streaming.attribution_aggregation",
            "from ..application import execution",
            True,
            id="aggregation-cannot-import-application",
        ),
        pytest.param(
            "foghttp_benchmark.streaming.attribution_window",
            "from foghttp_benchmark.report_publication import publish_report",
            True,
            id="attribution-window-cannot-import-publication",
        ),
        pytest.param(
            "foghttp_benchmark.rendering",
            "from typing import TYPE_CHECKING as types_only\n"
            "if types_only:\n"
            "    from foghttp_benchmark.models import BenchmarkArgs",
            False,
            id="rendering-allows-model-types-through-guard-alias",
        ),
        pytest.param(
            "foghttp_benchmark.rendering",
            "import typing as t\nif t.TYPE_CHECKING:\n    import foghttp_benchmark.compare.models as comparison_models",
            False,
            id="rendering-allows-comparison-types-through-typing-alias",
        ),
        pytest.param(
            "foghttp_benchmark.statistics",
            "from .constants import MIN_VARIATION_SAMPLES",
            False,
            id="statistics-allows-neutral-constants",
        ),
        pytest.param(
            "foghttp_benchmark.streaming.lifecycle",
            "from .lifecycle_models import LifecycleConfig",
            False,
            id="lifecycle-orchestration-allows-owned-models",
        ),
        pytest.param(
            "foghttp_benchmark.streaming.suite",
            "from ..report_publication import publish_report",
            False,
            id="suite-orchestration-may-publish-prepared-reports",
        ),
        pytest.param(
            "foghttp_benchmark.compare.reports",
            "from typer import BadParameter",
            False,
            id="comparison-command-adapter-may-use-typer",
        ),
        pytest.param(
            "foghttp_benchmark.isolation.reports",
            "from ..report_finalization import MergedSuiteReport",
            False,
            id="isolation-allows-neutral-finalization-contract",
        ),
        pytest.param(
            "foghttp_benchmark.streaming.attribution_validation",
            "from ..validity.reports import metadata_with_validity",
            False,
            id="data-preparation-allows-validity-metadata-owner",
        ),
    ],
)
def test_boundary_policy_rejects_forbidden_imports_and_preserves_allowed_composition(
    module: str,
    source: str,
    *,
    forbidden: bool,
) -> None:
    violations = boundary_violations(module, source)

    assert bool(violations) is forbidden, f"{module}\n{source}\n{violations}"
