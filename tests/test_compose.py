import pytest

from env_contract.compose import COMPOSE_FILES, read_compose_names
from env_contract.errors import ParseError


def names_for(write_project, text: str, filename: str = "compose.yaml"):
    return read_compose_names(str(write_project({filename: text})))


@pytest.mark.parametrize("filename", COMPOSE_FILES)
def test_every_supported_file_name_is_found(write_project, filename):
    names, warnings = names_for(write_project, "services:\n  a:\n    environment: [FOUND]\n", filename)
    assert names == {"FOUND"}
    assert warnings == []


def test_no_compose_file_returns_none(write_project):
    assert read_compose_names(str(write_project({"compose.yaml.bak": "services: {}\n"}))) == (None, [])


def test_nested_compose_files_are_not_used(write_project):
    project = write_project({"deploy/compose.yaml": "services:\n  a:\n    environment: [NESTED]\n"})
    assert read_compose_names(str(project)) == (None, [])


def test_first_file_wins_when_several_exist(write_project):
    project = write_project(
        {
            "docker-compose.yml": "services:\n  a:\n    environment: [LEGACY]\n",
            "compose.yaml": "services:\n  a:\n    environment: [PREFERRED]\n",
        }
    )
    names, warnings = read_compose_names(str(project))
    assert names == {"PREFERRED"}
    assert warnings == ["compose.yaml: used; also found docker-compose.yml (ignored)"]


def test_environment_list_form(write_project):
    text = (
        "services:\n"
        "  web:\n"
        "    environment:\n"
        "      - PASS_THROUGH\n"
        "      - WITH_VALUE=literal\n"
        "      - EMPTY_VALUE=\n"
        "      - \"QUOTED=a=b\"\n"
    )
    names, warnings = names_for(write_project, text)
    assert names == {"PASS_THROUGH", "WITH_VALUE", "EMPTY_VALUE", "QUOTED"}
    assert warnings == []


def test_environment_mapping_form(write_project):
    text = (
        "services:\n"
        "  web:\n"
        "    environment:\n"
        "      MAPPED: value\n"
        "      NULL_VALUE:\n"
        "      NUMBER: 3\n"
    )
    names, warnings = names_for(write_project, text)
    assert names == {"MAPPED", "NULL_VALUE", "NUMBER"}
    assert warnings == []


@pytest.mark.parametrize(
    "value, expected",
    [
        ("${BRACED}", {"BRACED"}),
        ("${WITH_DEFAULT:-fallback}", {"WITH_DEFAULT"}),
        ("${UNSET_DEFAULT-fallback}", {"UNSET_DEFAULT"}),
        ("${REQUIRED:?must be set}", {"REQUIRED"}),
        ("${ALT:+alt}", {"ALT"}),
        ("${OUTER:-${INNER}}", {"OUTER", "INNER"}),
        ("prefix-$BARE-suffix", {"BARE"}),
        ("$$ESCAPED $${ALSO_ESCAPED}", set()),
        ("$$$${STILL_ESCAPED}", set()),
        ("$${ESCAPED} ${REAL}", {"REAL"}),
        ("no interpolation, cost $5", set()),
    ],
)
def test_interpolations(write_project, value, expected):
    text = f"services:\n  web:\n    image: example\n    command: ['sh', '-c', '{value}']\n"
    names, _ = names_for(write_project, text)
    assert names == expected


def test_interpolations_anywhere_in_values_but_not_keys(write_project):
    text = (
        "name: ${PROJECT_NAME}\n"
        "services:\n"
        "  web:\n"
        "    image: \"repo/web:${TAG:-latest}\"\n"
        "    ports:\n"
        "      - \"${HOST_PORT}:80\"\n"
        "    labels:\n"
        "      ${KEY_NOT_INTERPOLATED}: x\n"
        "    environment:\n"
        "      DB_URL: postgres://${DB_USER}@db/app\n"
        "volumes:\n"
        "  data:\n"
        "    name: ${VOLUME_NAME}\n"
    )
    names, _ = names_for(write_project, text)
    assert names == {"PROJECT_NAME", "TAG", "HOST_PORT", "DB_URL", "DB_USER", "VOLUME_NAME"}


def test_comments_are_not_scanned(write_project):
    text = "# ${IN_COMMENT}\nservices:\n  web:\n    image: x  # $ALSO_COMMENT\n"
    names, _ = names_for(write_project, text)
    assert names == set()


def test_anchors_and_merge_keys(write_project):
    text = (
        "x-env: &shared-env\n"
        "  environment:\n"
        "    FROM_ANCHOR: \"1\"\n"
        "x-list: &shared-list\n"
        "  - FROM_ALIAS\n"
        "services:\n"
        "  inherits:\n"
        "    <<: *shared-env\n"
        "    image: a\n"
        "  overrides:\n"
        "    <<: *shared-env\n"
        "    image: b\n"
        "    environment:\n"
        "      OWN: \"1\"\n"
        "  aliased:\n"
        "    environment: *shared-list\n"
        "  merged_mapping:\n"
        "    environment:\n"
        "      <<: {MERGED_IN_ENV: a}\n"
        "      LOCAL: b\n"
    )
    names, warnings = names_for(write_project, text)
    assert names == {"FROM_ANCHOR", "OWN", "FROM_ALIAS", "MERGED_IN_ENV", "LOCAL"}
    assert warnings == []


def test_compose_specific_tags_are_accepted(write_project):
    text = (
        "services:\n"
        "  web:\n"
        "    environment: !override\n"
        "      - TAGGED\n"
        "    ports: !reset []\n"
    )
    names, warnings = names_for(write_project, text)
    assert names == {"TAGGED"}
    assert warnings == []


def test_structural_problems_are_warnings(write_project):
    text = (
        "services:\n"
        "  empty:\n"
        "  scalar_service: nope\n"
        "  no_env:\n"
        "    image: x\n"
        "  null_env:\n"
        "    environment:\n"
        "  scalar_env:\n"
        "    environment: FOO=bar\n"
        "  odd_entries:\n"
        "    environment:\n"
        "      - GOOD\n"
        "      - [nested]\n"
        "      - \"not a name\"\n"
    )
    names, warnings = names_for(write_project, text)
    assert names == {"GOOD"}
    assert warnings == [
        "compose.yaml:3: service is not a mapping",
        "compose.yaml:9: 'environment' is neither a list nor a mapping",
        "compose.yaml:13: unsupported 'environment' entry, ignored",
        "compose.yaml:14: unsupported 'environment' entry, ignored",
    ]


@pytest.mark.parametrize(
    "text, warning",
    [
        ("", "compose.yaml: empty file"),
        ("# only a comment\n", "compose.yaml: empty file"),
        ("- a\n- b\n", "compose.yaml:1: top level is not a mapping"),
        ("services: [a]\n", "compose.yaml:1: 'services' is not a mapping"),
    ],
)
def test_unexpected_top_level_is_a_warning(write_project, text, warning):
    names, warnings = names_for(write_project, text)
    assert names == set()
    assert warnings == [warning]


@pytest.mark.parametrize(
    "text, line",
    [
        ("services:\n  web:\n    image: x\n   bad: indent\n", 4),
        ("services:\n  web:\n    environment: [A, B\n", 4),
        ("services:\n\tweb: {}\n", 2),
        ("services:\n  web:\n    image: \"unterminated\n", 4),
        ("services: *undefined_anchor\n", 1),
        ("a: 1\n---\nb: 2\n", 2),
    ],
)
def test_invalid_yaml_is_a_parse_error_with_line(write_project, text, line):
    with pytest.raises(ParseError) as info:
        names_for(write_project, text)
    assert info.value.path == "compose.yaml"
    assert info.value.line == line
    assert str(info.value).startswith(f"compose.yaml:{line}: invalid YAML: ")
