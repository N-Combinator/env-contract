import json
import os
import subprocess
import sys

import pytest

from env_contract.compose import COMPOSE_FILES


def test_full_fixture_reports_all_three_differences(fixture_project, check_json):
    project = fixture_project("full")
    # Vendored code is skipped, even when it would not parse.
    (project / ".venv" / "lib").mkdir(parents=True)
    (project / ".venv" / "lib" / "site.py").write_text('import os\nos.getenv("FROM_VENV")\ndef broken(:\n')
    (project / "node_modules" / "pkg").mkdir(parents=True)
    (project / "node_modules" / "pkg" / "x.py").write_text('import os\nos.getenv("FROM_NODE_MODULES")\n')

    code, report = check_json(project)

    assert list(report) == ["missing_in_template", "unused_in_code", "undeclared_in_compose", "warnings"]
    assert report["missing_in_template"] == ["IMAGE_TAG", "LOG_LEVEL"]
    assert report["unused_in_code"] == ["UNUSED_TEMPLATE_VAR"]
    assert report["undeclared_in_compose"] == ["LEGACY_MODE", "PORT", "SENTRY_DSN", "UNUSED_TEMPLATE_VAR"]
    assert report["warnings"] == [
        "app/settings.py:21: dynamic name in os.getenv() ignored",
        "app/settings.py:25: dynamic name in os.environ.get() ignored",
        "app/settings.py:25: dynamic name in os.environ[...] ignored",
        "app/settings.py:25: dynamic name in 'in os.environ' ignored",
        ".env.example:13: not a KEY=value line, ignored",
    ]
    assert code == 1


def test_consistent_project_exits_zero(fixture_project, check_json):
    code, report = check_json(fixture_project("clean"))
    assert report == {
        "missing_in_template": [],
        "unused_in_code": [],
        "undeclared_in_compose": [],
        "warnings": [],
    }
    assert code == 0


def test_no_compose_file_gives_null_and_a_warning(fixture_project, check_json):
    code, report = check_json(fixture_project("no_compose"))
    assert report["missing_in_template"] == []
    assert report["unused_in_code"] == []
    assert report["undeclared_in_compose"] is None
    assert report["warnings"] == [
        "no compose file found (looked for compose.yaml, compose.yml, docker-compose.yaml, docker-compose.yml)"
    ]
    assert code == 0


def test_missing_template_is_a_warning_not_an_error(fixture_project, check_json):
    code, report = check_json(fixture_project("no_template"))
    assert report == {
        "missing_in_template": ["WORKERS"],
        "unused_in_code": [],
        "undeclared_in_compose": [],
        "warnings": [".env.example: not found"],
    }
    assert code == 1


@pytest.mark.parametrize(
    "files, key",
    [
        # Only (A ∪ C) − B is non-empty.
        ({"a.py": 'import os\nos.getenv("X")\n', "compose.yaml": "services:\n  s:\n    environment: [X]\n"},
         "missing_in_template"),
        # Only B − A is non-empty (compose absent, so undeclared_in_compose is null).
        ({".env.example": "X=\n"}, "unused_in_code"),
        # Only (A ∪ B) − C is non-empty.
        ({"a.py": 'import os\nos.getenv("X")\n', ".env.example": "X=\n", "compose.yaml": "services: {}\n"},
         "undeclared_in_compose"),
    ],
)
def test_any_single_difference_exits_one(write_project, check_json, files, key):
    code, report = check_json(write_project(files))
    non_empty = [k for k in ("missing_in_template", "unused_in_code", "undeclared_in_compose") if report[k]]
    assert non_empty == [key]
    assert report[key] == ["X"]
    assert code == 1


def test_empty_project_exits_zero_with_warnings(write_project, check_json):
    code, report = check_json(write_project({}))
    assert report["undeclared_in_compose"] is None
    assert len(report["warnings"]) == 2
    assert code == 0


def test_malformed_python_exits_two_with_path_and_line(fixture_project, run):
    code, out, err = run("check", fixture_project("bad_python"), "--json")
    assert code == 2
    assert out == ""
    assert err.startswith("env-contract: error: pkg/broken.py:3: ")


def test_malformed_compose_exits_two_with_path_and_line(fixture_project, run):
    code, out, err = run("check", fixture_project("bad_compose"), "--json")
    assert code == 2
    assert out == ""
    assert err.startswith("env-contract: error: compose.yaml:6: invalid YAML: ")


@pytest.mark.parametrize("command", ["check", "template"])
@pytest.mark.parametrize("fixture", ["bad_python", "bad_compose"])
def test_parse_errors_exit_two_for_both_commands(fixture_project, run, command, fixture):
    code, out, _ = run(command, fixture_project(fixture))
    assert code == 2
    assert out == ""


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["unknown"],
        ["check"],
        ["check", "--json"],
        ["template"],
        ["check", ".", "--bogus"],
    ],
)
def test_usage_errors_exit_two(run, argv):
    code, out, err = run(*argv)
    assert code == 2
    assert "usage:" in err


def test_project_must_be_a_directory(run, tmp_path):
    code, _, err = run("check", tmp_path / "missing", "--json")
    assert code == 2
    assert "not a directory" in err
    (tmp_path / "file.py").write_text("")
    code, _, err = run("template", tmp_path / "file.py")
    assert code == 2


def test_template_prints_union_sorted_without_values(fixture_project, run):
    project = fixture_project("full")
    code, out, err = run("template", project)
    lines = out.splitlines()
    assert lines[0] == "# Environment variables for full (generated by env-contract; values left blank)"
    assert lines[1:] == [
        "DATABASE_URL=",
        "DEBUG=",
        "FEATURE_FLAG=",
        "IMAGE_TAG=",
        "LEGACY_MODE=",
        "LOG_LEVEL=",
        "PORT=",
        "REDIS_URL=",
        "SECRET_KEY=",
        "SENTRY_DSN=",
        "TIMEOUT=",
        "UNUSED_TEMPLATE_VAR=",
    ]
    # Values present in .env.example and compose.yaml are never echoed.
    assert "postgres://" not in out and "redis://" not in out
    assert "warning: app/settings.py:21: dynamic name in os.getenv() ignored" in err
    assert code == 0


def test_template_with_no_names_prints_only_the_header(write_project, run):
    code, out, _ = run("template", write_project({}))
    assert out.count("\n") == 1 and out.startswith("# ")
    assert code == 0


def test_text_output_without_json(fixture_project, run):
    code, out, _ = run("check", fixture_project("no_template"))
    assert "missing_in_template: 1" in out
    assert "  WORKERS" in out
    assert "warning: .env.example: not found" in out
    assert code == 1
    code, out, _ = run("check", fixture_project("no_compose"))
    assert "undeclared_in_compose: skipped (no compose file)" in out
    assert code == 0


@pytest.mark.parametrize("filename", COMPOSE_FILES)
def test_each_compose_name_is_used_by_check(write_project, check_json, filename):
    project = write_project(
        {"a.py": 'import os\nos.getenv("X")\n', ".env.example": "X=\n", filename: "services:\n  s:\n    environment: [X]\n"}
    )
    code, report = check_json(project)
    assert report["undeclared_in_compose"] == []
    assert code == 0


def test_console_entry_point_as_a_real_process(fixture_project):
    project = fixture_project("full")
    proc = subprocess.run(
        [sys.executable, "-m", "env_contract", "check", str(project), "--json"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert json.loads(proc.stdout)["unused_in_code"] == ["UNUSED_TEMPLATE_VAR"]
    proc = subprocess.run([sys.executable, "-m", "env_contract", "check"], capture_output=True, text=True)
    assert proc.returncode == 2


requires_non_root = pytest.mark.skipif(
    not hasattr(os, "geteuid") or os.geteuid() == 0, reason="root can read files with mode 000"
)


@pytest.mark.parametrize("target", ["missing.py", "loop.py"])
def test_broken_python_symlink_is_skipped_with_a_warning(write_project, check_json, target):
    project = write_project({"a.py": 'import os\nos.getenv("A")\n', ".env.example": "A=\n"})
    (project / "pkg").mkdir()
    os.symlink(target, project / "pkg" / "loop.py")  # "loop.py" points at itself
    code, report = check_json(project)
    assert report["missing_in_template"] == []
    assert report["warnings"][0] == "pkg/loop.py: skipped, broken symlink"
    assert code == 0


@requires_non_root
@pytest.mark.parametrize("command", ["check", "template"])
@pytest.mark.parametrize("rel", ["pkg/a.py", ".env.example", "compose.yaml"])
def test_unreadable_file_exits_two_with_path(write_project, run, command, rel):
    project = write_project(
        {
            "pkg/a.py": 'import os\nos.getenv("A")\n',
            ".env.example": "A=\n",
            "compose.yaml": "services:\n  web:\n    environment: [A]\n",
        }
    )
    (project / rel).chmod(0)
    try:
        code, out, err = run(command, project, "--json") if command == "check" else run(command, project)
    finally:
        (project / rel).chmod(0o644)
    assert code == 2
    assert out == ""
    assert err == f"env-contract: error: {rel}: cannot read file: Permission denied\n"


def test_unexpected_os_error_exits_two(write_project, run, monkeypatch):
    project = write_project({"a.py": "x = 1\n"})

    def fail(project):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("env_contract.python_source.scan_project", fail)
    code, out, err = run("check", project, "--json")
    assert (code, out, err) == (2, "", "env-contract: error: Permission denied\n")
