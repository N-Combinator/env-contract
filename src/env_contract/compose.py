"""Set C: names wired into a Compose file.

The file is parsed with PyYAML's ``compose()`` into a node tree rather than
loaded into Python objects: nodes carry line numbers for warnings, and Compose
specific tags such as ``!reset`` / ``!override`` need no constructors.
"""

import os
import re

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from env_contract import safe_io
from env_contract.errors import ParseError

COMPOSE_FILES = ("compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml")
MERGE_TAG = "tag:yaml.org,2002:merge"
NULL_TAG = "tag:yaml.org,2002:null"
NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# `$$` is an escaped dollar; `${NAME...}` and `$NAME` are interpolations.
# Nested defaults such as `${A:-${B}}` are found because scanning continues
# right after the name.
INTERPOLATION_RE = re.compile(r"\$(?:\$|\{([A-Za-z_][A-Za-z0-9_]*)|([A-Za-z_][A-Za-z0-9_]*))")


def find_compose_file(project: str) -> tuple[str | None, list[str]]:
    present = [n for n in COMPOSE_FILES if os.path.isfile(os.path.join(project, n))]
    if not present:
        return None, []
    warnings = []
    if len(present) > 1:
        warnings.append(f"{present[0]}: used; also found {', '.join(present[1:])} (ignored)")
    return present[0], warnings


def read_compose_names(project: str) -> tuple[set[str] | None, list[str]]:
    """Return ``(names, warnings)``; ``names`` is None when no compose file exists."""
    filename, warnings = find_compose_file(project)
    if filename is None:
        return None, warnings
    data = safe_io.read_project_file(project, filename)
    try:
        root = yaml.compose(data, Loader=yaml.SafeLoader)
    except yaml.YAMLError as exc:
        raise _parse_error(filename, exc) from None

    names: set[str] = set()
    if root is None:
        warnings.append(f"{filename}: empty file")
        return names, warnings
    if not isinstance(root, MappingNode):
        warnings.append(f"{filename}:{_line(root)}: top level is not a mapping")
        return names, warnings

    _collect_interpolations(root, names)
    services = _mapping(root).get("services")
    if services is not None:
        if isinstance(services, MappingNode):
            for service in _mapping(services).values():
                _collect_service(filename, service, names, warnings)
        elif not _is_null(services):
            warnings.append(f"{filename}:{_line(services)}: 'services' is not a mapping")
    return names, warnings


def _collect_service(filename: str, service: Node, names: set[str], warnings: list[str]) -> None:
    if not isinstance(service, MappingNode):
        if not _is_null(service):
            warnings.append(f"{filename}:{_line(service)}: service is not a mapping")
        return
    env = _mapping(service).get("environment")
    if env is None or _is_null(env):
        return
    if isinstance(env, MappingNode):
        entries = list(_mapping(env, keys=True).values())
    elif isinstance(env, SequenceNode):
        entries = env.value
    else:
        warnings.append(f"{filename}:{_line(env)}: 'environment' is neither a list nor a mapping")
        return
    for node in entries:
        if isinstance(node, ScalarNode):
            name = node.value.split("=", 1)[0].strip()
            if NAME_RE.fullmatch(name):
                names.add(name)
                continue
        warnings.append(f"{filename}:{_line(node)}: unsupported 'environment' entry, ignored")


def _mapping(node: MappingNode, keys: bool = False, _depth: int = 0) -> dict:
    """Scalar-keyed view of a mapping with YAML merge keys (``<<``) applied.

    Explicit keys win over merged ones, and earlier merge sources win over later
    ones. With ``keys=True`` the values are the key nodes instead.
    """
    result: dict = {}
    merged: list[Node] = []
    for key, value in node.value:
        if key.tag == MERGE_TAG:
            merged.extend(value.value if isinstance(value, SequenceNode) else [value])
        elif isinstance(key, ScalarNode):
            result[key.value] = key if keys else value
    if _depth < 50:
        for source in merged:
            if isinstance(source, MappingNode):
                for k, v in _mapping(source, keys, _depth + 1).items():
                    result.setdefault(k, v)
    return result


def _collect_interpolations(root: Node, names: set[str]) -> None:
    seen: set[int] = set()
    stack = [root]
    while stack:
        node = stack.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        if isinstance(node, ScalarNode):
            for match in INTERPOLATION_RE.finditer(node.value):
                name = match.group(1) or match.group(2)
                if name:
                    names.add(name)
        elif isinstance(node, SequenceNode):
            stack.extend(node.value)
        elif isinstance(node, MappingNode):
            # Compose interpolates values, not keys.
            stack.extend(value for _, value in node.value)


def _is_null(node: Node) -> bool:
    return isinstance(node, ScalarNode) and node.tag == NULL_TAG


def _line(node: Node) -> int:
    return node.start_mark.line + 1


def _parse_error(filename: str, exc: yaml.YAMLError) -> ParseError:
    mark = getattr(exc, "problem_mark", None) or getattr(exc, "context_mark", None)
    line = mark.line + 1 if mark is not None else None
    message = getattr(exc, "problem", None) or str(exc).splitlines()[0]
    return ParseError(filename, line, f"invalid YAML: {message}")
