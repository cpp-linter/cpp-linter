import json
import logging
from os import environ
from pathlib import Path
import requests_mock
import pytest

from cpp_linter.rest_api.github_api import GithubApiClient
from cpp_linter.clang_tools import capture_clang_tools_output
from cpp_linter.clang_tools.clang_tidy import TidyNotification
from cpp_linter.common_fs import list_source_files
from cpp_linter.loggers import logger

TEST_REPO = "cpp-linter/test-cpp-linter-action"
TEST_PR = 22
TEST_SHA = "8d68756375e0483c7ac2b4d6bbbece420dbbb495"


@pytest.mark.parametrize("event_name", ["pull_request", "push"])
@pytest.mark.parametrize(
    "thread_comments,no_lgtm",
    [
        ("update", True),
        ("update", False),
        ("true", True),
        ("true", False),
        ("false", True),
        ("false", False),
        pytest.param("fail", False, marks=pytest.mark.xfail),
    ],
    ids=[
        "updated-lgtm",
        "updated-no_lgtm",
        "new-lgtm",
        "new-no_lgtm",
        "disabled-lgtm",
        "disabled-no_lgtm",
        "no_token",
    ],
)
def test_post_feedback(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
    event_name: str,
    thread_comments: str,
    no_lgtm: bool,
):
    """A mock test of posting comments and step summary"""
    files = list_source_files(
        extensions=["cpp", "hpp"],
        ignored=["tests/capture_tools_output"],
        not_ignored=[],
    )
    assert files
    format_advice, tidy_advice = capture_clang_tools_output(
        files,
        version=environ.get("CLANG_VERSION", "16"),
        checks="readability-*,modernize-*,clang-analyzer-*,cppcoreguidelines-*",
        style="llvm",
        lines_changed_only=0,
        database="",
        extra_args=[],
        tidy_review=False,
        format_review=False,
        num_workers=None,
    )
    # add a non project file to tidy_advice to intentionally cover a log.debug()
    assert tidy_advice
    tidy_advice[-1].notes.append(
        TidyNotification(
            notification_line=(
                "/usr/include/stdio.h",
                33,
                10,
                "error",
                "'stddef.h' file not found",
                "clang-diagnostic-error",
            ),
        )
    )

    # patch env vars
    event_payload = {"number": TEST_PR, "repository": {"private": False}}
    event_payload_path = tmp_path / "event_payload.json"
    event_payload_path.write_text(json.dumps(event_payload), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_payload_path))
    monkeypatch.setenv("CI", "true")
    if thread_comments != "fail":
        monkeypatch.setenv("GITHUB_TOKEN", "123456")
    summary_path = tmp_path / "step_summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))

    gh_client = GithubApiClient()
    gh_client.repo = TEST_REPO
    gh_client.sha = TEST_SHA
    gh_client.event_name = event_name

    with requests_mock.Mocker() as mock:
        cache_path = Path(__file__).parent
        base_url = f"{gh_client.api_url}/repos/{TEST_REPO}/"

        if event_name == "pull_request":
            # load mock responses for pull_request event
            mock.get(
                f"{base_url}issues/{TEST_PR}",
                text=(cache_path / f"pr_{TEST_PR}.json").read_text(encoding="utf-8"),
            )
            comments_url = f"{base_url}issues/{TEST_PR}/comments"
            for i in [1, 2]:
                mock.get(
                    f"{comments_url}?page={i}&per_page=100",
                    text=(cache_path / f"pr_comments_pg{i}.json").read_text(
                        encoding="utf-8"
                    ),
                    headers=(
                        {}
                        if i == 2
                        else {
                            "link": f'<{comments_url}?page=2&per_page=100>; rel="next"'
                        }
                    ),
                )
        else:
            # load mock responses for push event
            mock.get(
                f"{base_url}commits/{TEST_SHA}",
                text=(cache_path / f"push_{TEST_SHA}.json").read_text(encoding="utf-8"),
            )
            mock.get(
                f"{base_url}commits/{TEST_SHA}/comments",
                text=(cache_path / f"push_comments_{TEST_SHA}.json").read_text(
                    encoding="utf-8"
                ),
            )

        # acknowledge any DELETE, PATCH, and POST requests about specific comments
        comment_url = f"{base_url}comments/"
        comment_id = 76453652
        mock.delete(f"{comment_url}{comment_id}")
        mock.patch(f"{comment_url}{comment_id}")
        mock.post(f"{base_url}commits/{TEST_SHA}/comments")
        mock.post(f"{base_url}issues/{TEST_PR}/comments")

        # to get debug files saved to test workspace folders: enable logger verbosity
        caplog.set_level(logging.DEBUG, logger=logger.name)

        gh_client.post_feedback(
            files,
            format_advice,
            tidy_advice,
            thread_comments,
            no_lgtm,
            step_summary=thread_comments == "update" and not no_lgtm,
            file_annotations=thread_comments == "update" and no_lgtm,
            style="llvm",
            tidy_review=False,
            format_review=False,
        )
