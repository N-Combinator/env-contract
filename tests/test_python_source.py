import ast
import warnings

import pytest

from env_contract.errors import ParseError
from env_contract.python_source import _EnvVisitor, scan_project


def scan(write_project, source: str, filename: str = "app.py"):
    return scan_project(str(write_project({filename: source})))


@pytest.mark.parametrize(
    "source",
    [
        'import os\nos.getenv("NAME")\n',
        'import os\nos.getenv("NAME", "default")\n',
        'import os\nos.getenv(key="NAME", default=None)\n',
        'import os\nos.environ.get("NAME")\n',
        'import os\nos.environ.get("NAME", "default")\n',
        'import os\nos.environ["NAME"]\n',
        'import os\nif "NAME" in os.environ:\n    pass\n',
        'import os\nif "NAME" not in os.environ:\n    pass\n',
        'import os as o\no.getenv("NAME")\n',
        'from os import getenv\ngetenv("NAME")\n',
        'from os import getenv as ge\nge("NAME")\n',
        'from os import environ\nenviron["NAME"]\n',
        'from os import environ as env\nenv.get("NAME")\n',
        'from os import environ\n"NAME" in environ\n',
    ],
)
def test_extraction_forms(write_project, source):
    result = scan(write_project, source)
    assert result.names == {"NAME"}
    assert result.warnings == []


@pytest.mark.parametrize(
    "source, form",
    [
        ("import os\nname = 'X'\nos.getenv(name)\n", "os.getenv()"),
        ("import os\nname = 'X'\nos.getenv(f'{name}_URL', 'd')\n", "os.getenv()"),
        ("import os\nargs = ['X']\nos.getenv(*args)\n", "os.getenv()"),
        ("import os\nname = 'X'\nos.environ.get(name)\n", "os.environ.get()"),
        ("import os\nname = 'X'\nos.environ['A' + name]\n", "os.environ[...]"),
        ("import os\nname = 'X'\nname in os.environ\n", "'in os.environ'"),
    ],
)
def test_dynamic_names_are_ignored_with_a_warning(write_project, source, form):
    result = scan(write_project, source, filename="pkg/dyn.py")
    assert result.names == set()
    assert result.warnings == [f"pkg/dyn.py:3: dynamic name in {form} ignored"]


def test_writes_deletes_and_lookalikes_are_not_reads(write_project):
    source = (
        "import os\n"
        "os.environ['SET_FOR_CHILD'] = '1'\n"
        "os.environ['AUG'] += 'x'\n"
        "del os.environ['DELETED']\n"
        "d = {}\n"
        "d.get('DICT_GET')\n"
        "d['DICT_ITEM']\n"
        "'IN_DICT' in d\n"
        "os.path.join('NOT_ENV')\n"
        "os.environ.setdefault('SETDEFAULT', '1')\n"
    )
    result = scan(write_project, source)
    assert result.names == set()
    assert result.warnings == []


def test_recursive_and_skips_vendored_directories(write_project):
    project = write_project(
        {
            "a.py": 'import os\nos.getenv("TOP")\n',
            "pkg/sub/b.py": 'import os\nos.getenv("NESTED")\n',
            "pkg/not_python.txt": 'os.getenv("TEXT_FILE")\n',
            # Skipped directories, anywhere in the tree; broken files prove they are never parsed.
            ".venv/lib/site.py": 'import os\nos.getenv("FROM_DOT_VENV")\ndef broken(:\n',
            "venv/lib/site.py": 'import os\nos.getenv("FROM_VENV")\n',
            "web/node_modules/x/y.py": 'import os\nos.getenv("FROM_NODE_MODULES")\n',
            ".git/hooks/hook.py": 'import os\nos.getenv("FROM_GIT")\n',
            "pkg/.venv/z.py": "def broken(:\n",
        }
    )
    result = scan_project(str(project))
    assert result.names == {"TOP", "NESTED"}


def test_syntax_error_reports_path_and_line(write_project):
    project = write_project({"ok.py": "x = 1\n", "pkg/bad.py": "import os\n\n\nif True\n    pass\n"})
    with pytest.raises(ParseError) as info:
        scan_project(str(project))
    assert info.value.path == "pkg/bad.py"
    assert info.value.line == 4
    assert str(info.value).startswith("pkg/bad.py:4: ")


def test_null_bytes_are_a_parse_error(write_project, tmp_path):
    project = write_project({})
    (project / "nul.py").write_bytes(b"x = 1\x00\n")
    with pytest.raises(ParseError) as info:
        scan_project(str(project))
    assert info.value.path == "nul.py"


def test_python_file_with_dotenv_name_is_skipped(write_project):
    project = write_project({".env.py": 'import os\nos.getenv("NEVER")\n', "a.py": 'import os\nos.getenv("A")\n'})
    result = scan_project(str(project))
    assert result.names == {"A"}
    assert result.warnings == [".env.py: skipped, dotenv-style file names are never opened"]


def test_virtual_environments_are_skipped_whatever_their_name(write_project):
    project = write_project(
        {
            "a.py": 'import os\nos.getenv("A")\n',
            # pyvenv.cfg marks a virtual environment root; broken files prove nothing inside is parsed.
            "env/pyvenv.cfg": "home = /usr/bin\n",
            "env/lib/site.py": 'import os\nos.getenv("FROM_ENV")\ndef broken(:\n',
            ".env/pyvenv.cfg": "home = /usr/bin\n",
            ".env/lib/site.py": 'import os\nos.getenv("FROM_DOT_ENV")\n',
            "tools/py311/pyvenv.cfg": "home = /usr/bin\n",
            "tools/py311/bin/x.py": "def broken(:\n",
            # Only the directory holding pyvenv.cfg is a venv root; its parent is still scanned.
            "pkg/b.py": 'import os\nos.getenv("B")\n',
            "pkg/data/pyvenv.cfg": "not a marker for pkg\n",
            "pkg/data/c.py": 'import os\nos.getenv("NOT_SCANNED")\n',
        }
    )
    result = scan_project(str(project))
    assert result.names == {"A", "B"}
    assert result.warnings == []


@pytest.mark.parametrize("depth", [2_000, 100_000])  # overflows the tree walk / the parser itself
def test_deeply_nested_file_is_skipped_with_a_warning(write_project, depth):
    project = write_project(
        {
            "a.py": 'import os\nos.getenv("A")\n',
            "pkg/deep.py": 'import os\nos.getenv("DEEP")\nx = ' + "a + " * depth + "a\n",
        }
    )
    result = scan_project(str(project))
    assert result.names == {"A"}
    assert result.warnings == ["pkg/deep.py: skipped, too deeply nested to analyse"]


@pytest.mark.parametrize("error", [RecursionError, MemoryError])
@pytest.mark.parametrize("owner, attr", [(ast, "parse"), (_EnvVisitor, "visit")])
def test_overflow_in_parse_or_walk_is_a_warning(write_project, monkeypatch, error, owner, attr):
    project = write_project({"a.py": 'import os\nos.getenv("A")\n', "b.py": 'import os\nos.getenv("B")\n'})
    original = getattr(owner, attr)
    calls = []

    def overflow_once(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise error("too deep")
        return original(*args, **kwargs)

    monkeypatch.setattr(owner, attr, overflow_once)
    result = scan_project(str(project))
    assert result.names == {"B"}
    assert result.warnings == ["a.py: skipped, too deeply nested to analyse"]


def test_syntax_warnings_from_scanned_code_are_suppressed(write_project):
    project = write_project({"a.py": 'import os\nos.getenv("A")\npattern = "\\d+"\n'})
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = scan_project(str(project))
    assert result.names == {"A"}
    assert [str(w.message) for w in caught] == []
