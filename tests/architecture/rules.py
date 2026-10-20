from tests.architecture.imports import import_references


ROOT = "foghttp_benchmark"
UI = (f"{ROOT}.cli", f"{ROOT}._child")
PRESENTATION = (f"{ROOT}.rendering", f"{ROOT}.report_publication")
MEASUREMENT_NAMES = {
    "runner",
    "load",
    "measurement",
    "client_io",
    "operations_sync",
    "operations_async",
    "consume",
    "attribution_consume",
    "attribution_measure",
    "lifecycle_consume",
    "lifecycle_controls",
    "lifecycle_worker",
}
STREAMING_DATA = {
    "report_values",
    "lifecycle_aggregation",
    "attribution_aggregation",
    "attribution_validation",
    "attribution_window",
}


def within(target: str, module: str) -> bool:
    return target == module or target.startswith(module + ".")


def writer_reference(target: str) -> bool:
    if within(target, f"{ROOT}.validity.reports"):
        return False
    return any(part == "reports" or part.endswith("_reports") for part in target.split("."))


def boundary_violations(module: str, source: str, *, is_package: bool = False) -> list[str]:
    violations = []
    name = module.rsplit(".", maxsplit=1)[-1]
    application = within(module, f"{ROOT}.application")
    orchestration = name in {"suite", "request_suite"} or module == f"{ROOT}.streaming.lifecycle"
    isolation = within(module, f"{ROOT}.isolation")
    measurement = name in MEASUREMENT_NAMES
    parsing = (
        within(module, f"{ROOT}.report_schema")
        or within(module, f"{ROOT}.validity")
        or module in {f"{ROOT}.validation", f"{ROOT}.compare.loading", f"{ROOT}.compare.analysis"}
        or (module.startswith(f"{ROOT}.streaming.") and name in STREAMING_DATA)
    )
    for reference in import_references(module, source, is_package=is_package):
        target = reference.target
        project = within(target, ROOT)
        ui = any(within(target, prefix) for prefix in UI)
        presentation = any(within(target, prefix) for prefix in PRESENTATION)
        application_target = within(target, f"{ROOT}.application")
        cli_framework = target.split(".")[0] in {"typer", "click", "argparse"}
        report = project and writer_reference(target)
        broken = []
        if module in {f"{ROOT}.statistics", f"{ROOT}.rendering", f"{ROOT}.report_publication"} and (
            project or cli_framework
        ):
            allowed = (module == f"{ROOT}.statistics" and within(target, f"{ROOT}.constants")) or (
                module == f"{ROOT}.rendering"
                and reference.type_only
                and any(within(target, allowed_type) for allowed_type in (f"{ROOT}.models", f"{ROOT}.compare.models"))
            )
            if not allowed:
                broken.append("shared")
        if application and (ui or cli_framework):
            broken.append("application")
        if orchestration and (ui or application_target):
            broken.append("orchestration")
        if isolation and (
            ui
            or application_target
            or (project and any(part in {"suite", "request_suite", "finalization"} for part in target.split(".")))
        ):
            broken.append("isolation")
        if measurement and (
            ui or application_target or presentation or report or within(target, f"{ROOT}.validity.reports")
        ):
            broken.append("measurement")
        if parsing and (ui or application_target or presentation or report):
            broken.append("parsing")
        violations.extend(f"{module}:{reference.line}: {rule}: {target}" for rule in broken)
    return violations
