"""Tests that focus on the ``ignore`` option's parsing."""
from pathlib import Path
from typing import List
import pytest
from cpp_linter.cli import parse_ignore_option
from cpp_linter.common_fs import is_file_in_list


@pytest.mark.parametrize(
    "user_in,is_ignored,is_not_ignored",
    [
        (
            "src|!src/file.h|!",
            ["src/file.h", "src/sub/path/file.h"],
            ["src/file.h", "file.h"],
        ),
        (
            "!src|./",
            ["file.h", "sub/path/file.h"],
            ["src/file.h", "src/sub/path/file.h"],
        ),
    ],
)
def test_ignore(
    caplog: pytest.LogCaptureFixture,
    user_in: str,
    is_ignored: List[str],
    is_not_ignored: List[str],
):
    """test ignoring of a specified path."""
    caplog.set_level(10)
    ignored, not_ignored = parse_ignore_option(user_in, [])
    for p in is_ignored:
        assert is_file_in_list(ignored, p, "ignored")
    for p in is_not_ignored:
        assert is_file_in_list(not_ignored, p, "not ignored")


def test_ignore_submodule(monkeypatch: pytest.MonkeyPatch):
    """test auto detection of submodules and ignore the paths appropriately."""
    monkeypatch.chdir(str(Path(__file__).parent))
    ignored, not_ignored = parse_ignore_option("!pybind11", [])
    for ignored_submodule in ["RF24", "RF24Network", "RF24Mesh"]:
        assert ignored_submodule in ignored
    assert "pybind11" in not_ignored


@pytest.mark.parametrize(
    "user_input", [[], ["file1", "file2"]], ids=["none", "multiple"]
)
def test_positional_arg(user_input: List[str]):
    """Make sure positional arg value(s) are added to not_ignored list."""
    _, not_ignored = parse_ignore_option("", user_input)
    assert user_input == not_ignored
