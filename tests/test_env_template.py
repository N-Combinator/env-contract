from env_contract.env_template import read_template_keys


def test_keys_are_parsed_without_values(write_project):
    project = write_project(
        {
            ".env.example": (
                "# a comment\n"
                "\n"
                "PLAIN=value\n"
                "EMPTY=\n"
                "  INDENTED = spaced\n"
                "export EXPORTED=1\n"
                "BARE_KEY\n"
                "QUOTED=\"with = sign\"\n"
                "lower_case_ok=1\n"
            )
        }
    )
    keys, warnings = read_template_keys(str(project))
    assert keys == {"PLAIN", "EMPTY", "INDENTED", "EXPORTED", "BARE_KEY", "QUOTED", "lower_case_ok"}
    assert warnings == []


def test_invalid_lines_warn_without_echoing_content(write_project):
    project = write_project({".env.example": "OK=1\n9STARTS_WITH_DIGIT=hunter2\nnot a key hunter2\n"})
    keys, warnings = read_template_keys(str(project))
    assert keys == {"OK"}
    assert warnings == [
        ".env.example:2: not a KEY=value line, ignored",
        ".env.example:3: not a KEY=value line, ignored",
    ]
    assert "hunter2" not in "".join(warnings)


def test_missing_template_returns_none(write_project):
    keys, warnings = read_template_keys(str(write_project({})))
    assert keys is None
    assert warnings == []


def test_utf8_bom_is_not_part_of_the_first_key(write_project):
    project = write_project({})
    (project / ".env.example").write_bytes(b"\xef\xbb\xbfFIRST=1\nSECOND=\n")
    keys, warnings = read_template_keys(str(project))
    assert keys == {"FIRST", "SECOND"}
    assert warnings == []
