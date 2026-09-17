import json
import shutil
from pathlib import Path

import pytest

from env_contract.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_project(tmp_path):
    """Copy a fixture project into a temporary directory and return its path."""

    def copy(name: str) -> Path:
        target = tmp_path / name
        shutil.copytree(FIXTURES / name, target)
        return target

    return copy


@pytest.fixture
def write_project(tmp_path):
    """Create a project from a ``{relative path: text}`` mapping."""

    def write(files: dict[str, str], name: str = "project") -> Path:
        root = tmp_path / name
        root.mkdir()
        for rel, text in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        return root

    return write


@pytest.fixture
def run(capsys):
    """Run the CLI in-process; return ``(exit_code, stdout, stderr)``."""

    def invoke(*argv: str) -> tuple[int, str, str]:
        code = main([str(a) for a in argv])
        out, err = capsys.readouterr()
        return code, out, err

    return invoke


@pytest.fixture
def check_json(run):
    def invoke(project) -> tuple[int, dict]:
        code, out, err = run("check", project, "--json")
        assert err == ""
        return code, json.loads(out)

    return invoke
