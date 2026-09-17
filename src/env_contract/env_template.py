"""Set B: keys declared in ``<project>/.env.example``. Values are never kept."""

import os
import re

from env_contract import safe_io

NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def read_template_keys(project: str) -> tuple[set[str] | None, list[str]]:
    """Return ``(keys, warnings)``; ``keys`` is None when the file does not exist."""
    path = os.path.join(project, safe_io.TEMPLATE_NAME)
    if not os.path.isfile(path):
        return None, []
    text = safe_io.read_project_file(project, safe_io.TEMPLATE_NAME).decode("utf-8", errors="replace")
    keys: set[str] = set()
    warnings: list[str] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        name = line.split("=", 1)[0].strip()
        if NAME_RE.fullmatch(name):
            keys.add(name)
        else:
            # The line itself is not echoed: it could carry a value.
            warnings.append(f"{safe_io.TEMPLATE_NAME}:{lineno}: not a KEY=value line, ignored")
    return keys, warnings
