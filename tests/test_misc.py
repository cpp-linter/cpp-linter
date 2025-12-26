"""Tests that complete coverage that aren't prone to failure."""

import logging
import os
import json
from pathlib import Path
import shutil
from typing import List, cast

import pytest

from cpp_linter.common_fs import get_line_cnt_from_cols, FileObj
from cpp_linter.common_fs.file_filter import FileFilter
from cpp_linter.clang_tools import assemble_version_exec
from cpp_linter.loggers import (
    logger,
    log_commander,
    start_log_group,
    end_log_group,
)
from cpp_linter.rest_api.github_api import GithubApiClient
from cpp_linter.clang_tools.clang_tidy import TidyNotification


@pytest.mark.no_clang
def test_exit_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Test exit code that indicates if action encountered lining errors."""
    env_file = tmp_path / "GITHUB_OUTPUT"
    monkeypatch.setenv("GITHUB_OUTPUT", str(env_file))
    gh_client = GithubApiClient()
    tidy_checks_failed = 1
    format_checks_failed = 2
    checks_failed = 3
    assert 3 == gh_client.set_exit_code(
        checks_failed, format_checks_failed, tidy_checks_failed
    )
    output = env_file.read_text(encoding="utf-8")
    assert f"checks-failed={checks_failed}\n" in output
    assert f"format-checks-failed={format_checks_failed}\n" in output
    assert f"tidy-checks-failed={tidy_checks_failed}\n" in output


# see https://github.com/pytest-dev/pytest/issues/5997
@pytest.mark.no_clang
def test_end_group(caplog: pytest.LogCaptureFixture):
    """Test the output that concludes a group of runner logs."""
    caplog.set_level(logging.INFO, logger=log_commander.name)
    log_commander.propagate = True
    end_log_group()
    messages = caplog.messages
    assert "::endgroup::" in messages


# see https://github.com/pytest-dev/pytest/issues/5997
@pytest.mark.no_clang
def test_start_group(caplog: pytest.LogCaptureFixture):
    """Test the output that begins a group of runner logs."""
    caplog.set_level(logging.INFO, logger=log_commander.name)
    log_commander.propagate = True
    start_log_group("TEST")
    messages = caplog.messages
    assert "::group::TEST" in messages


@pytest.mark.parametrize(
    "extensions",
    [
        (["cpp", "hpp", "yml"]),  # yml included to traverse .github folder
        pytest.param(["cxx"], marks=pytest.mark.xfail),
    ],
)
@pytest.mark.no_clang
def test_list_src_files(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    extensions: List[str],
):
    """List the source files in the root folder of this repo."""
    monkeypatch.chdir(Path(__file__).parent.parent.as_posix())
    caplog.set_level(logging.DEBUG, logger=logger.name)
    file_filter = FileFilter(extensions=extensions)
    files = file_filter.list_source_files()
    assert files
    for file in files:
        assert Path(file.name).suffix.lstrip(".") in extensions


@pytest.mark.no_clang
@pytest.mark.parametrize("line,cols,offset", [(13, 5, 144), (19, 1, 189)])
def test_file_offset_translation(line: int, cols: int, offset: int):
    """Validate output from ``get_line_cnt_from_cols()``"""
    contents = Path("tests/demo/demo.cpp").read_bytes()
    assert (line, cols) == get_line_cnt_from_cols(contents, offset)


@pytest.mark.no_clang
def test_serialize_file_obj():
    """Validate JSON serialization of a FileObj instance."""
    file_obj = FileObj("some_name", [5, 10], [2, 12])
    json_obj = (
        r'[{"filename": "some_name", "line_filter": {"diff_chunks": [2, 12], '
        + r'"lines_added": [[5, 5], [10, 10]]}}]'
    )
    assert json.dumps([file_obj.serialize()]) == json_obj


CLANG_VERSION = os.getenv("CLANG_VERSION", "12")

DEFAULT_CLANG_FORMAT_EXE = cast(str, shutil.which("clang-format"))


@pytest.mark.parametrize("tool_name", ["clang-format"])
@pytest.mark.parametrize(
    "version",
    [
        CLANG_VERSION,
        str(Path(DEFAULT_CLANG_FORMAT_EXE).parent),
        str(Path(DEFAULT_CLANG_FORMAT_EXE).parent.parent),
        "",
    ],
    ids=["number", "path", "distant_parent_path", "none"],
)
def test_tool_exe_path(tool_name: str, version: str):
    """Test specifying the version of the clang tool."""
    exe_path = assemble_version_exec(tool_name, version)
    assert exe_path
    assert tool_name in exe_path


def test_clang_analyzer_link():
    """Ensures the hyper link for a diagnostic about clang-analyzer checks is
    not malformed"""
    file_name = "RF24.cpp"
    line = "1504"
    column = "9"
    rationale = "Dereference of null pointer (loaded from variable 'pipe_num')"
    severity = "warning"
    diagnostic_name = "clang-analyzer-core.NullDereference"
    note = TidyNotification(
        (
            file_name,
            line,
            column,
            severity,
            rationale,
            diagnostic_name,
        )
    )
    assert note.diagnostic_link == (
        "[{}]({}/{}.html)".format(
            diagnostic_name,
            "https://clang.llvm.org/extra/clang-tidy/checks/clang-analyzer",
            diagnostic_name.split("-", maxsplit=2)[2],
        )
    )


@pytest.mark.no_clang
def test_diagnostic_link_no_hyphen() -> None:
    """Test that diagnostic_link returns diagnostic name if no hyphen is present."""
    note = TidyNotification(
        (
            "test.cpp",
            1,
            1,
            "error",
            "Test rationale",
            "no_diagnostic_name",
        )
    )
    assert note.diagnostic_link == "no_diagnostic_name"
