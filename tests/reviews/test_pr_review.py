import json
from os import environ
from pathlib import Path
import shutil
import requests_mock
import pytest

from cpp_linter.rest_api.github_api import GithubApiClient
from cpp_linter.clang_tools import capture_clang_tools_output

TEST_REPO = "cpp-linter/test-cpp-linter-action"
TEST_PR = 27
DEFAULT_TIDY_CHECKS = (
    "boost-*,bugprone-*,performance-*,readability-*,portability-*,modernize-*,"
    "clang-analyzer-*,cppcoreguidelines-*"
)


@pytest.mark.parametrize(
    "is_draft,is_closed,with_token,force_approved,tidy_review,format_review,changes,summary_only,no_lgtm",
    [
        (True, False, True, False, False, True, 2, False, False),
        (False, True, True, False, False, True, 2, False, False),
        pytest.param(
            False,
            False,
            False,
            False,
            False,
            True,
            2,
            False,
            False,
            marks=pytest.mark.xfail,
        ),
        (False, False, True, True, False, True, 2, False, False),
        (False, False, True, False, True, False, 2, False, True),
        (False, False, True, False, True, False, 2, False, False),
        (False, False, True, False, False, True, 2, False, False),
        (False, False, True, False, True, True, 1, False, False),
        (False, False, True, False, True, True, 0, False, False),
        (False, False, True, False, True, True, 0, True, False),
    ],
    ids=[
        "draft",
        "closed",
        "no_token",
        "approved",
        "no_lgtm",
        "tidy",  # changes == diff_chunks only
        "format",  # changes == diff_chunks only
        "lines_added",
        "all_lines",
        "summary_only",
    ],
)
def test_post_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    is_draft: bool,
    is_closed: bool,
    with_token: bool,
    tidy_review: bool,
    format_review: bool,
    force_approved: bool,
    changes: int,
    summary_only: bool,
    no_lgtm: bool,
):
    """A mock test of posting PR reviews"""
    # patch env vars
    event_payload = {"number": TEST_PR, "repository": {"private": False}}
    event_payload_path = tmp_path / "event_payload.json"
    event_payload_path.write_text(json.dumps(event_payload), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_payload_path))
    monkeypatch.setenv("CI", "true")
    if with_token:
        monkeypatch.setenv("GITHUB_TOKEN", "123456")
    if summary_only:
        monkeypatch.setenv("CPP_LINTER_PR_REVIEW_SUMMARY_ONLY", "true")
    monkeypatch.chdir(str(tmp_path))
    (tmp_path / "src").mkdir()
    demo_dir = Path(__file__).parent.parent / "demo"
    shutil.copyfile(str(demo_dir / "demo.cpp"), str(tmp_path / "src" / "demo.cpp"))
    shutil.copyfile(str(demo_dir / "demo.hpp"), str(tmp_path / "src" / "demo.hpp"))
    cache_path = Path(__file__).parent
    shutil.copyfile(
        str(cache_path / ".clang-format"), str(tmp_path / "src" / ".clang-format")
    )
    shutil.copyfile(
        str(cache_path / ".clang-tidy"), str(tmp_path / "src" / ".clang-tidy")
    )

    gh_client = GithubApiClient()
    gh_client.repo = TEST_REPO
    gh_client.event_name = "pull_request"

    with requests_mock.Mocker() as mock:
        base_url = f"{gh_client.api_url}/repos/{TEST_REPO}/pulls/{TEST_PR}"
        # load mock responses for pull_request event
        mock.get(
            base_url,
            headers={"Accept": "application/vnd.github.diff"},
            text=(cache_path / f"pr_{TEST_PR}.diff").read_text(encoding="utf-8"),
        )
        reviews = (cache_path / "pr_reviews.json").read_text(encoding="utf-8")
        mock.get(
            f"{base_url}/reviews",
            text=reviews,
            # to trigger a logged error, we'll modify the status code here
            status_code=404 if tidy_review and not format_review else 200,
        )
        mock.get(
            f"{base_url}/comments",
            text=(cache_path / "pr_review_comments.json").read_text(encoding="utf-8"),
        )

        # acknowledge any PUT and POST requests about specific reviews
        mock.post(f"{base_url}/reviews")
        for review_id in [r["id"] for r in json.loads(reviews) if "id" in r]:
            mock.put(f"{base_url}/reviews/{review_id}/dismissals")

        # run the actual test
        files = gh_client.get_list_of_changed_files(
            extensions=["cpp", "hpp"],
            ignored=[],
            not_ignored=[],
            lines_changed_only=changes,
        )
        assert files
        for file_obj in files:
            assert file_obj.diff_chunks
        if force_approved:
            files.clear()

        format_advice, tidy_advice = capture_clang_tools_output(
            files,
            version=environ.get("CLANG_VERSION", "16"),
            checks=DEFAULT_TIDY_CHECKS,
            style="file",
            lines_changed_only=changes,
            database="",
            extra_args=[],
            tidy_review=tidy_review,
            format_review=format_review,
        )
        if not force_approved:
            assert [note for concern in tidy_advice for note in concern.notes]
            assert [note for note in format_advice]

        # simulate draft PR by changing the request response
        cache_pr_response = (cache_path / f"pr_{TEST_PR}.json").read_text(
            encoding="utf-8"
        )
        if is_draft:
            cache_pr_response = cache_pr_response.replace(
                '  "draft": false,', '  "draft": true,', 1
            )
        if is_closed:
            cache_pr_response = cache_pr_response.replace(
                '  "state": "open",', '  "state": "closed",', 1
            )
        mock.get(
            base_url,
            headers={"Accept": "application/vnd.github.text+json"},
            text=cache_pr_response,
        )
        gh_client.post_feedback(
            files,
            format_advice,
            tidy_advice,
            thread_comments="false",
            no_lgtm=no_lgtm,
            step_summary=False,
            file_annotations=False,
            style="file",
            tidy_review=tidy_review,
            format_review=format_review,
        )

        # inspect the review payload for correctness
        last_request = mock.last_request
        if (
            (tidy_review or format_review)
            and not is_draft
            and with_token
            and not is_closed
            and not no_lgtm
        ):
            assert hasattr(last_request, "json")
            json_payload = last_request.json()
            assert "body" in json_payload
            assert "event" in json_payload
            if tidy_review:
                assert "clang-tidy" in json_payload["body"]
            elif format_review:
                assert "clang-format" in json_payload["body"]
            else:  # pragma: no cover
                raise RuntimeError("review payload is incorrect")
            if force_approved:
                assert json_payload["event"] == "APPROVE"
            else:
                assert json_payload["event"] == "REQUEST_CHANGES"

            # save the body of the review json for manual inspection
            assert hasattr(last_request, "text")
            (tmp_path / "review.json").write_text(
                json.dumps(json_payload, indent=2), encoding="utf-8"
            )
