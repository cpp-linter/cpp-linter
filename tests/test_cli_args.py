"""Tests related parsing input from CLI arguments."""

from typing import List, Union
import pytest
from cpp_linter.cli import get_cli_parser, Args


@pytest.mark.no_clang
@pytest.mark.parametrize(
    "arg_name,arg_value,attr_name,attr_value",
    [
        ("verbosity", "10", "verbosity", True),
        ("database", "build", "database", "build"),
        ("style", "file", "style", "file"),
        ("tidy-checks", "-*", "tidy_checks", "-*"),
        ("version", "14", "version", "14"),
        ("extensions", ".cpp, .h", "extensions", ["cpp", "h"]),
        ("extensions", "cxx,.hpp", "extensions", ["cxx", "hpp"]),
        ("repo-root", "src", "repo_root", "src"),
        ("ignore", "!src|", "ignore", "!src|"),
        ("lines-changed-only", "True", "lines_changed_only", 2),
        ("lines-changed-only", "difF", "lines_changed_only", 1),
        ("files-changed-only", "True", "files_changed_only", True),
        ("thread-comments", "true", "thread_comments", "true"),
        ("thread-comments", "false", "thread_comments", "false"),
        ("thread-comments", "update", "thread_comments", "update"),
        ("no-lgtm", "true", "no_lgtm", True),
        ("no-lgtm", "false", "no_lgtm", False),
        ("step-summary", "True", "step_summary", True),
        ("file-annotations", "False", "file_annotations", False),
        ("extra-arg", "-std=c++17", "extra_arg", ["-std=c++17"]),
        ("extra-arg", '"-std=c++17 -Wall"', "extra_arg", ['"-std=c++17 -Wall"']),
        ("tidy-review", "true", "tidy_review", True),
        ("format-review", "true", "format_review", True),
        ("jobs", "0", "jobs", None),
        ("jobs", "1", "jobs", 1),
        ("jobs", "4", "jobs", 4),
        pytest.param("jobs", "x", "jobs", 0, marks=pytest.mark.xfail),
        ("ignore-tidy", "!src|", "ignore_tidy", "!src|"),
    ],
)
def test_arg_parser(
    arg_name: str,
    arg_value: str,
    attr_name: str,
    attr_value: Union[int, str, List[str], bool, None],
):
    """parameterized test of specific args compared to their parsed value"""
    args = get_cli_parser().parse_args([f"--{arg_name}={arg_value}"], namespace=Args())
    assert getattr(args, attr_name) == attr_value
    assert args.command is None


@pytest.mark.no_clang
def test_version_cmd():
    """Invoke `cpp-linter version` subcommand"""
    args = get_cli_parser().parse_args(["version"], namespace=Args())
    assert args.command == "version"
