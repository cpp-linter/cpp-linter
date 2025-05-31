"""Tests that focus on the ``ignore`` option's parsing."""

from pathlib import Path, PurePath
from typing import List
import pytest
from cpp_linter.common_fs.file_filter import FileFilter


@pytest.mark.parametrize(
    "user_in,is_ignored,is_not_ignored",
    [
        (
            "src | !src/file.h |!",
            ["src/file.h", "src/sub/path/file.h"],
            ["src/file.h", "file.h"],
        ),
        (
            "! src | ./",
            ["file.h", "sub/path/file.h"],
            ["src/file.h", "src/sub/path/file.h"],
        ),
        (
            "tests/** | !tests/demo| ! cpp_linter/*.py|",
            [
                "tests/test_misc.py",
                "tests/ignored_paths",
                "tests/ignored_paths/.gitmodules",
            ],
            ["tests/demo/demo.cpp", "tests/demo", "cpp_linter/__init__.py"],
        ),
        (
            "examples/*/build | !src",
            ["examples/linux/build/some/file.c"],
            ["src/file.h", "src/sub/path/file.h"],
        ),
    ],
)
@pytest.mark.no_clang
def test_ignore(
    caplog: pytest.LogCaptureFixture,
    user_in: str,
    is_ignored: List[str],
    is_not_ignored: List[str],
):
    """test ignoring of a specified path."""
    caplog.set_level(10)
    file_filter = FileFilter(ignore_value=user_in)
    for p in is_ignored:
        assert file_filter.is_file_in_list(ignored=True, file_name=PurePath(p))
    for p in is_not_ignored:
        assert file_filter.is_file_in_list(ignored=False, file_name=PurePath(p))


@pytest.mark.no_clang
def test_ignore_submodule(monkeypatch: pytest.MonkeyPatch):
    """test auto detection of submodules and ignore the paths appropriately."""
    monkeypatch.chdir(str(Path(__file__).parent))
    file_filter = FileFilter(ignore_value="!pybind11")
    file_filter.parse_submodules()
    for ignored_submodule in ["RF24", "RF24Network", "RF24Mesh"]:
        assert ignored_submodule in file_filter.ignored
    assert "pybind11" in file_filter.not_ignored


@pytest.mark.parametrize(
    "user_input", [[], ["file1", "file2"]], ids=["none", "multiple"]
)
@pytest.mark.no_clang
def test_positional_arg(user_input: List[str]):
    """Make sure positional arg value(s) are added to not_ignored list."""
    file_filter = FileFilter(not_ignored=user_input)
    assert set(user_input) == file_filter.not_ignored
