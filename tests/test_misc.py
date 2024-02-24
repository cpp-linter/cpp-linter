"""Tests that complete coverage that aren't prone to failure."""
import logging
import os
import json
from pathlib import Path
import shutil
from typing import List, cast

import pytest
import requests_mock

from cpp_linter.common_fs import (
    get_line_cnt_from_cols,
    FileObj,
    list_source_files,
)
from cpp_linter.clang_tools import assemble_version_exec
from cpp_linter.loggers import (
    logger,
    log_commander,
    start_log_group,
    end_log_group,
)
import cpp_linter.rest_api.github_api
from cpp_linter.rest_api.github_api import GithubApiClient


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
    "extensions",
    [
        (["cpp", "hpp", "yml"]),  # yml included to traverse .github folder
        pytest.param(["cxx"], marks=pytest.mark.xfail),
    ],
)
def test_list_src_files(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    extensions: List[str],
):
    """List the source files in the root folder of this repo."""
    monkeypatch.chdir(Path(__file__).parent.parent.as_posix())
    caplog.set_level(logging.DEBUG, logger=logger.name)
    files = list_source_files(extensions=extensions, ignored=[], not_ignored=[])
    assert files
    for file in files:
        assert Path(file.name).suffix.lstrip(".") in extensions


@pytest.mark.parametrize(
    "pseudo,expected_url,fake_runner",
    [
        (
            dict(
                repo="cpp-linter/test-cpp-linter-action",
                sha="708a1371f3a966a479b77f1f94ec3b7911dffd77",
                event_name="unknown",  # let coverage include logged warning
            ),
            "{rest_api_url}/repos/{repo}/commits/{sha}",
            True,
        ),
        (
            dict(
                repo="cpp-linter/test-cpp-linter-action",
                event_name="pull_request",
            ),
            "{rest_api_url}/repos/{repo}/pulls/{number}",
            True,
        ),
        ({}, "", False),
    ],
    ids=["push", "pull_request", "local_dev"],
)
def test_get_changed_files(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    pseudo: dict,
    expected_url: str,
    fake_runner: bool,
):
    """test getting a list of changed files for an event.

    This is expected to fail if a github token not supplied as an env var.
    We don't need to supply one for this test because the tested code will
    execute anyway.
    """
    caplog.set_level(logging.DEBUG, logger=logger.name)
    # setup test to act as though executed in user's repo's CI
    monkeypatch.setenv("CI", str(fake_runner).lower())
    gh_client = GithubApiClient()
    for name, value in pseudo.items():
        setattr(gh_client, name, value)
    if "event_name" in pseudo and pseudo["event_name"] == "pull_request":
        gh_client.event_payload = dict(number=19)
    if not fake_runner:
        # getting a diff in CI (on a shallow checkout) fails
        # monkey patch the .git.get_diff() to return nothing
        monkeypatch.setattr(
            cpp_linter.rest_api.github_api, "get_diff", lambda *args: ""
        )
    monkeypatch.setenv("GITHUB_TOKEN", "123456")

    with requests_mock.Mocker() as mock:
        mock.get(
            expected_url.format(number=19, rest_api_url=gh_client.api_url, **pseudo),
            request_headers={"Authorization": "token 123456"},
            text="",
        )

        files = gh_client.get_list_of_changed_files([], [], [], 0)
        assert not files


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
