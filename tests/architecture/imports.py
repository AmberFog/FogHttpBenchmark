import ast
from dataclasses import dataclass
from importlib.util import resolve_name


@dataclass(frozen=True, slots=True)
class ImportReference:
    target: str
    line: int
    type_only: bool


def import_references(module: str, source: str, *, is_package: bool = False) -> list[ImportReference]:
    """Read static imports, including local imports and the two typing guards."""
    tree = ast.parse(source)
    scanner = ImportScanner(module if is_package else module.rpartition(".")[0], tree)
    scanner.visit(tree)
    return scanner.references


class ImportScanner(ast.NodeVisitor):
    def __init__(self, package: str, tree: ast.Module) -> None:
        self.package = package
        self.references: list[ImportReference] = []
        self.type_depth = 0
        self.type_guards = {
            alias.asname or alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "typing"
            for alias in node.names
            if alias.name == "TYPE_CHECKING"
        }
        self.typing_names = {
            alias.asname or alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
            if alias.name == "typing"
        }

    def visit_Import(self, node: ast.Import) -> None:
        self.references.extend(ImportReference(alias.name, node.lineno, self.type_depth > 0) for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        base = node.module or ""
        if node.level:
            base = resolve_name("." * node.level + base, self.package)
        self.references.extend(
            ImportReference(base if alias.name == "*" else f"{base}.{alias.name}", node.lineno, self.type_depth > 0)
            for alias in node.names
        )

    def visit_If(self, node: ast.If) -> None:
        test = node.test
        guarded = (isinstance(test, ast.Name) and test.id in self.type_guards) or (
            isinstance(test, ast.Attribute)
            and test.attr == "TYPE_CHECKING"
            and isinstance(test.value, ast.Name)
            and test.value.id in self.typing_names
        )
        if not guarded:
            self.generic_visit(node)
            return
        self.type_depth += 1
        for statement in node.body:
            self.visit(statement)
        self.type_depth -= 1
        for statement in node.orelse:
            self.visit(statement)
