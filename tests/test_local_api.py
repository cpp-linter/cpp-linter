"""Tests for running outside GitHub Actions (locally or in another CI system)."""

import logging
from pathlib import Path

import pytest
import requests_mock

from cpp_linter import select_client
from cpp_linter.clang_tools import ClangVersions
from cpp_linter.clang_tools.clang_format import FormatAdvice, FormatReplacementLine
from cpp_linter.clang_tools.clang_tidy import TidyAdvice, TidyNotification
from cpp_linter.cli import Args
from cpp_linter.common_fs import FileObj
from cpp_linter.common_fs.file_filter import FileFilter
from cpp_linter.loggers import log_commander, logger
from cpp_linter.rest_api.github_api import GithubApiClient
from cpp_linter.rest_api.local_api import LocalApiClient
import cpp_linter.rest_api.local_api

TEST_DIFF = (Path(__file__).parent / "list_changes" / "patch.diff").read_text(
    encoding="utf-8"
)


@pytest.mark.no_clang
@pytest.mark.parametrize(
    "env,expected",
    [
        ({"GITHUB_ACTIONS": "true", "CI": "true"}, GithubApiClient),
        (
            {"GITEA_ACTIONS": "true", "GITHUB_ACTIONS": "true", "CI": "true"},
            LocalApiClient,
        ),
        ({"GITLAB_CI": "true", "CI": "true"}, LocalApiClient),
        ({"CI": "true"}, LocalApiClient),
        ({}, LocalApiClient),
    ],
    ids=["github-actions", "gitea-actions", "gitlab-ci", "other-ci", "local"],
)
def test_select_client(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    env: dict[str, str],
    expected: type,
):
    """Only GitHub Actions gets the GitHub client; Gitea Actions gets a warning."""
    names = ("GITHUB_ACTIONS", "GITEA_ACTIONS", "GITLAB_CI", "CI", "GITHUB_EVENT_PATH")
    for name in names:
        monkeypatch.setenv(name, "")
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    caplog.set_level(logging.WARNING, logger=log_commander.name)
    monkeypatch.setattr(log_commander, "propagate", True)
    client = select_client()
    assert isinstance(client, expected)
    gitea_warned = any("Gitea Actions is not supported" in m for m in caplog.messages)
    assert gitea_warned == ("GITEA_ACTIONS" in env)


@pytest.mark.no_clang
def test_changed_files_from_git(monkeypatch: pytest.MonkeyPatch):
    """In another CI system, changed files come from git, not the GitHub API."""
    monkeypatch.setenv("GITHUB_ACTIONS", "")
    monkeypatch.setenv("GITLAB_CI", "true")
    monkeypatch.setenv("CI", "true")
    monkeypatch.setattr(
        cpp_linter.rest_api.local_api, "get_diff", lambda *args: TEST_DIFF
    )
    client = select_client()
    with requests_mock.Mocker() as mock:
        files = client.get_list_of_changed_files(
            FileFilter(extensions=["cpp", "hpp"]), lines_changed_only=1
        )
        assert not mock.called
    assert sorted(f.name for f in files) == ["src/demo.cpp", "src/demo.hpp"]
    client.verify_files_are_present(files)  # a no-op that must not raise


@pytest.mark.no_clang
def test_post_feedback(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
):
    """Feedback goes to the log and the summary file, never to GitHub's files."""
    monkeypatch.chdir(tmp_path)
    github_output = tmp_path / "github_output"
    step_summary = tmp_path / "step_summary"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(step_summary))

    file_obj = FileObj("src/demo.cpp")
    file_obj.tidy_advice = TidyAdvice(
        [
            TidyNotification(
                notification_line=(
                    "src/demo.cpp",
                    10,
                    5,
                    "warning",
                    "statement should be inside braces",
                    "readability-braces-around-statements",
                )
            )
        ]
    )
    file_obj.format_advice = FormatAdvice("src/demo.cpp")
    file_obj.format_advice.replaced_lines.append(FormatReplacementLine(3))

    args = Args()
    args.style = "file"
    args.thread_comments = "update"
    args.summary_output_file = str(tmp_path / "out" / "summary.md")

    caplog.set_level(logging.DEBUG, logger=log_commander.name)
    caplog.set_level(logging.DEBUG, logger=logger.name)
    monkeypatch.setattr(log_commander, "propagate", True)
    with requests_mock.Mocker() as mock:
        LocalApiClient().post_feedback([file_obj], args, ClangVersions())
        assert not mock.called

    messages = caplog.messages
    assert (
        "src/demo.cpp:10:5: warning: statement should be inside braces "
        "[readability-braces-around-statements]"
    ) in messages
    assert "src/demo.cpp: does not conform to Custom style guidelines (lines 3)" in (
        messages
    )
    assert not [msg for msg in messages if msg.startswith("::")]
    assert any("only posted when running in GitHub Actions" in m for m in messages)
    assert "clang-tidy" in Path(args.summary_output_file).read_text(encoding="utf-8")
    assert not github_output.exists()
    assert not step_summary.exists()


@pytest.mark.no_clang
def test_post_feedback_summary_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
):
    """A summary file that can't be written is logged, not raised."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "not-a-dir").write_text("", encoding="utf-8")
    args = Args()
    args.summary_output_file = str(tmp_path / "not-a-dir" / "summary.md")

    caplog.set_level(logging.DEBUG, logger=log_commander.name)
    monkeypatch.setattr(log_commander, "propagate", True)
    # a file without any advice is skipped
    LocalApiClient().post_feedback([FileObj("src/demo.cpp")], args, ClangVersions())
    assert any("Failed to write summary output file" in m for m in caplog.messages)
