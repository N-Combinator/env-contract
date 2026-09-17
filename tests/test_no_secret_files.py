"""Real dotenv files must never be opened, and their contents never printed."""

import builtins
import contextlib
import io
import os
import sys

import pytest

from env_contract.safe_io import is_forbidden_name

SENTINEL = "SENTINEL-SECRET-3f9c1e7a"

# Audit hooks cannot be removed, so one hook records into whichever list is active.
_recorder: list | None = None


def _audit(event, args):
    if event == "open" and _recorder is not None:
        _recorder.append(args[0])


sys.addaudithook(_audit)


@contextlib.contextmanager
def record_opens():
    """Collect every path opened inside the block, via an audit hook and a patched ``open``."""
    global _recorder
    paths: list = []
    real_open = builtins.open

    def recording_open(file, *args, **kwargs):
        paths.append(file)
        return real_open(file, *args, **kwargs)

    _recorder = paths
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(builtins, "open", recording_open)
        mp.setattr(io, "open", recording_open)
        try:
            yield paths
        finally:
            _recorder = None


def _plant_secrets(project):
    for name in (".env", ".env.local", ".env.production", "app/.env", "app/.env.test"):
        (project / name).write_text(f"SECRET_KEY={SENTINEL}\nPLANTED_ONLY_IN_DOTENV={SENTINEL}\n")


def _dotenv_opens(paths):
    names = [os.path.basename(os.fsdecode(p)) for p in paths if isinstance(p, (str, bytes, os.PathLike))]
    return [n for n in names if is_forbidden_name(n)]


@pytest.mark.parametrize(
    "argv",
    [
        ["check", "{p}", "--json"],
        ["check", "{p}"],
        ["template", "{p}"],
    ],
)
def test_planted_dotenv_files_are_never_opened_or_printed(fixture_project, run, argv):
    project = fixture_project("full")
    _plant_secrets(project)

    with record_opens() as opened_paths:
        code, out, err = run(*[a.format(p=project) for a in argv])

    assert code in (0, 1)
    assert SENTINEL not in out and SENTINEL not in err
    assert "PLANTED_ONLY_IN_DOTENV" not in out + err
    assert opened_paths, "the recorder saw no opens at all; the test would be vacuous"
    assert any(os.fsdecode(p).endswith(".env.example") for p in opened_paths if isinstance(p, (str, os.PathLike)))
    assert _dotenv_opens(opened_paths) == []


def test_template_symlinked_to_dotenv_is_refused(write_project, run):
    project = write_project({"a.py": 'import os\nos.getenv("A")\n'})
    (project / ".env").write_text(f"A={SENTINEL}\n")
    os.symlink(".env", project / ".env.example")

    with record_opens() as opened_paths:
        code, out, err = run("check", project, "--json")

    assert code == 2
    assert "refusing to open" in err
    assert SENTINEL not in out + err
    assert _dotenv_opens(opened_paths) == []
    assert all(not os.fsdecode(p).endswith(".env.example") for p in opened_paths if isinstance(p, (str, os.PathLike)))


def test_python_file_symlinked_to_dotenv_is_skipped(write_project, run):
    project = write_project({"a.py": 'import os\nos.getenv("A")\n', ".env.example": "A=\n"})
    (project / ".env").write_text(f"A={SENTINEL}\n")
    os.symlink(".env", project / "settings.py")

    with record_opens() as opened_paths:
        code, out, err = run("check", project, "--json")

    assert code == 0
    assert "settings.py: skipped, dotenv-style file names are never opened" in out
    assert SENTINEL not in out + err
    assert not any(os.fsdecode(p).endswith("settings.py") for p in opened_paths if isinstance(p, (str, os.PathLike)))


def test_forbidden_names():
    assert is_forbidden_name(".env")
    assert is_forbidden_name(".env.local")
    assert is_forbidden_name(".env.example.bak")
    assert not is_forbidden_name(".env.example")
    assert not is_forbidden_name("env.example")
    assert not is_forbidden_name(".envrc")
    assert not is_forbidden_name("settings.py")
