"""Set A: environment variable names read by Python code, found with ``ast``."""

import ast
import os
import warnings
from dataclasses import dataclass, field

from env_contract import safe_io
from env_contract.errors import ParseError

SKIP_DIRS = frozenset({".venv", "venv", "node_modules", ".git"})
# Present at the root of every virtual environment, whatever the directory is called.
VENV_MARKER = "pyvenv.cfg"


@dataclass
class ScanResult:
    names: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)


def _rel(project: str, path: str) -> str:
    return os.path.relpath(path, project).replace(os.sep, "/")


def _is_skipped_dir(dirpath: str, name: str) -> bool:
    return name in SKIP_DIRS or os.path.isfile(os.path.join(dirpath, name, VENV_MARKER))


def iter_python_files(project: str, warnings_out: list[str]):
    """Yield project-relative POSIX paths of ``*.py`` files, in sorted order.

    Directories that cannot be listed are reported in ``warnings_out``: their
    files are unknown, so the result would otherwise be silently incomplete.
    """

    def onerror(exc: OSError) -> None:
        rel = _rel(project, exc.filename) if exc.filename else "."
        warnings_out.append(f"{rel}: skipped, cannot read directory: {exc.strerror or exc}")

    for dirpath, dirnames, filenames in os.walk(project, onerror=onerror):
        dirnames[:] = sorted(d for d in dirnames if not _is_skipped_dir(dirpath, d))
        for name in sorted(filenames):
            if name.endswith(".py"):
                yield _rel(project, os.path.join(dirpath, name))


def scan_project(project: str) -> ScanResult:
    result = ScanResult()
    for rel in iter_python_files(project, result.warnings):
        full = os.path.join(project, rel)
        if safe_io.is_forbidden(full):
            result.warnings.append(f"{rel}: skipped, dotenv-style file names are never opened")
            continue
        if os.path.islink(full) and not os.path.exists(full):
            result.warnings.append(f"{rel}: skipped, broken symlink")
            continue
        source = safe_io.read_project_file(project, rel)
        try:
            # SyntaxWarning (e.g. invalid escape sequences) is about the scanned
            # project, not about env-contract; keep stderr clean.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                tree = ast.parse(source, filename=rel)
            visitor = _EnvVisitor(rel)
            visitor.visit(tree)
        except SyntaxError as exc:
            raise ParseError(rel, exc.lineno, exc.msg) from None
        except ValueError as exc:  # e.g. null bytes on Python < 3.12
            raise ParseError(rel, None, str(exc)) from None
        except (RecursionError, MemoryError):
            # Deeply nested code overflows the parser or the tree walk (the
            # parser reports its own stack overflow as MemoryError). The file
            # is valid Python, so it is skipped rather than failing the run.
            result.warnings.append(f"{rel}: skipped, too deeply nested to analyse")
            continue
        result.names |= visitor.names
        result.warnings.extend(visitor.warnings)
    return result


def _is_str(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


class _EnvVisitor(ast.NodeVisitor):
    """Collects names from ``os.getenv``, ``os.environ.get``, ``os.environ[...]``
    and ``... in os.environ``.

    Import aliases (``import os as o``, ``from os import environ, getenv``) are
    followed by name, without scope analysis.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self.names: set[str] = set()
        self.warnings: list[str] = []
        self.os_names = {"os"}
        self.environ_names: set[str] = set()
        self.getenv_names: set[str] = set()

    # -- import tracking -------------------------------------------------
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == "os":
                self.os_names.add(alias.asname or "os")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == "os" and node.level == 0:
            for alias in node.names:
                if alias.name == "environ":
                    self.environ_names.add(alias.asname or alias.name)
                elif alias.name == "getenv":
                    self.getenv_names.add(alias.asname or alias.name)

    # -- matching helpers ------------------------------------------------
    def _is_os_attr(self, node: ast.AST, attr: str) -> bool:
        return (
            isinstance(node, ast.Attribute)
            and node.attr == attr
            and isinstance(node.value, ast.Name)
            and node.value.id in self.os_names
        )

    def _is_environ(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            return node.id in self.environ_names
        return self._is_os_attr(node, "environ")

    def _is_getenv(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            return node.id in self.getenv_names
        return self._is_os_attr(node, "getenv")

    def _record(self, node: ast.AST | None, lineno: int, form: str) -> None:
        if node is not None and _is_str(node):
            self.names.add(node.value)
        else:
            self.warnings.append(
                f"{self.path}:{lineno}: dynamic name in {form} ignored"
            )

    # -- forms -----------------------------------------------------------
    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if self._is_getenv(func):
            self._record(_first_arg(node, "key"), node.lineno, "os.getenv()")
        elif (
            isinstance(func, ast.Attribute)
            and func.attr == "get"
            and self._is_environ(func.value)
        ):
            self._record(_first_arg(node, None), node.lineno, "os.environ.get()")
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        # Only reads count: assigning or deleting os.environ["X"] configures a
        # child process rather than requiring the variable from the operator.
        if isinstance(node.ctx, ast.Load) and self._is_environ(node.value):
            self._record(node.slice, node.lineno, "os.environ[...]")
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        left = node.left
        for op, right in zip(node.ops, node.comparators):
            if isinstance(op, (ast.In, ast.NotIn)) and self._is_environ(right):
                self._record(left, node.lineno, "'in os.environ'")
            left = right
        self.generic_visit(node)


def _first_arg(call: ast.Call, keyword: str | None) -> ast.AST | None:
    """The name argument of a call, or None when it cannot be determined."""
    if call.args:
        first = call.args[0]
        return None if isinstance(first, ast.Starred) else first
    for kw in call.keywords:
        if keyword is not None and kw.arg == keyword:
            return kw.value
    return None
