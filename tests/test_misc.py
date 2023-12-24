"""Tests that complete coverage that aren't prone to failure."""
import logging
import os
import json
from pathlib import Path
import shutil
from typing import List, cast
import pytest
import requests
import cpp_linter
import cpp_linter.run
from cpp_linter import (
    Globals,
    log_response_msg,
    get_line_cnt_from_cols,
    FileObj,
    assemble_version_exec,
)
from cpp_linter.run import (
    log_commander,
    start_log_group,
    end_log_group,
    set_exit_code,
    list_source_files,
    get_list_of_changed_files,
)


def test_exit_override(tmp_path: Path):
    """Test exit code that indicates if action encountered lining errors."""
    env_file = tmp_path / "GITHUB_OUTPUT"
    os.environ["GITHUB_OUTPUT"] = str(env_file)
    assert 1 == set_exit_code(1)
    assert env_file.read_text(encoding="utf-8").startswith("checks-failed=1\n")


def test_exit_implicit():
    """Test the exit code issued when a thread comment is to be made."""
    # fake values for total checks-failed
    Globals.tidy_failed_count = 1
    Globals.format_failed_count = 1
    assert 2 == set_exit_code()


# see https://github.com/pytest-dev/pytest/issues/5997
def test_end_group(caplog: pytest.LogCaptureFixture):
    """Test the output that concludes a group of runner logs."""
    caplog.set_level(logging.INFO, logger=log_commander.name)
    log_commander.propagate = True
    end_log_group()
    messages = caplog.messages
    assert "::endgroup::" in messages


# see https://github.com/pytest-dev/pytest/issues/5997
def test_start_group(caplog: pytest.LogCaptureFixture):
    """Test the output that begins a group of runner logs."""
    caplog.set_level(logging.INFO, logger=log_commander.name)
    log_commander.propagate = True
    start_log_group("TEST")
    messages = caplog.messages
    assert "::group::TEST" in messages


@pytest.mark.parametrize(
    "url",
    [
        ("https://github.com/orgs/cpp-linter/repositories"),
        pytest.param(("https://github.com/cpp-linter/repo"), marks=pytest.mark.xfail),
    ],
)
def test_response_logs(url: str):
    """Test the log output for a requests.response buffer."""
    Globals.response_buffer = requests.get(url)
    assert log_response_msg()


@pytest.mark.parametrize(
    "extensions",
    [
        (["cpp", "hpp"]),
        pytest.param(["cxx", "h"], marks=pytest.mark.xfail),
    ],
)
def test_list_src_files(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    extensions: List[str],
):
    """List the source files in the demo folder of this repo."""
    monkeypatch.setattr(Globals, "FILES", [])
    monkeypatch.chdir(Path(__file__).parent.as_posix())
    caplog.set_level(logging.DEBUG, logger=cpp_linter.logger.name)
    list_source_files(ext_list=extensions, ignored_paths=[], not_ignored=[])
    assert Globals.FILES
    for file in Globals.FILES:
        assert Path(file.name).suffix.lstrip(".") in extensions


@pytest.mark.parametrize(
    "pseudo,expected_url",
    [
        (
            dict(
                GITHUB_REPOSITORY="cpp-linter/test-cpp-linter-action",
                GITHUB_SHA="708a1371f3a966a479b77f1f94ec3b7911dffd77",
                GITHUB_EVENT_NAME="unknown",  # let coverage include logged warning
                IS_ON_RUNNER=True,
            ),
            "{GITHUB_API_URL}/repos/{GITHUB_REPOSITORY}/commits/{GITHUB_SHA}",
        ),
        (
            dict(
                GITHUB_REPOSITORY="cpp-linter/test-cpp-linter-action",
                GITHUB_EVENT_NAME="pull_request",
                IS_ON_RUNNER=True,
            ),
            "{GITHUB_API_URL}/repos/{GITHUB_REPOSITORY}/pulls/{number}",
        ),
        (dict(IS_ON_RUNNER=False), ""),
    ],
    ids=["push", "pull_request", "local_dev"],
)
def test_get_changed_files(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    pseudo: dict,
    expected_url: str,
):
    """test getting a list of changed files for an event.

    This is expected to fail if a github token not supplied as an env var.
    We don't need to supply one for this test because the tested code will
    execute anyway.
    """
    caplog.set_level(logging.DEBUG, logger=cpp_linter.logger.name)
    # setup test to act as though executed in user's repo's CI
    for name, value in pseudo.items():
        monkeypatch.setattr(cpp_linter.run, name, value)
    if "GITHUB_EVENT_NAME" in pseudo and pseudo["GITHUB_EVENT_NAME"] == "pull_request":
        monkeypatch.setattr(cpp_linter.run.Globals, "EVENT_PAYLOAD", dict(number=19))

    def fake_get(url: str, *args, **kwargs):  # pylint: disable=unused-argument
        """Consume the url and return a blank response."""
        assert (
            expected_url.format(
                number=19, GITHUB_API_URL=cpp_linter.run.GITHUB_API_URL, **pseudo
            )
            == url
        )
        fake_response = requests.Response()
        fake_response.url = url
        fake_response.status_code = 211
        fake_response._content = b""  # pylint: disable=protected-access
        return fake_response

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(cpp_linter.run, "get_diff", lambda *args: "")

    get_list_of_changed_files()
    assert not Globals.FILES


@pytest.mark.parametrize("line,cols,offset", [(13, 5, 144), (19, 1, 189)])
def test_file_offset_translation(line: int, cols: int, offset: int):
    """Validate output from ``get_line_cnt_from_cols()``"""
    test_file = str(Path("tests/demo/demo.cpp").resolve())
    assert (line, cols) == get_line_cnt_from_cols(test_file, offset)


def test_serialize_file_obj():
    """Validate JSON serialization of a FileObj instance."""
    file_obj = FileObj("some_name", [5, 10], [2, 12])
    json_obj = (
        r'[{"filename": "some_name", "line_filter": {"diff_chunks": [2, 12], '
        + r'"lines_added": [[5, 6], [10, 11]]}}]'
    )
    assert json.dumps([file_obj.serialize()]) == json_obj


CLANG_VERSION = os.getenv("CLANG_VERSION", "12")


@pytest.mark.parametrize("tool_name", ["clang-format"])
@pytest.mark.parametrize(
    "version",
    [CLANG_VERSION, str(Path(cast(str, shutil.which("clang-format"))).parent), ""],
    ids=["number", "path", "none"],
)
def test_tool_exe_path(tool_name: str, version: str):
    """Test specifying the version of the clang tool."""
    assert assemble_version_exec(tool_name, version)
