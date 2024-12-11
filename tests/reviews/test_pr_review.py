from collections import OrderedDict
import json
from os import environ
from pathlib import Path
import shutil
from typing import Dict, Any
import requests_mock
import pytest
import requests_mock.request
import requests_mock.response

from cpp_linter.rest_api.github_api import GithubApiClient
from cpp_linter.clang_tools import capture_clang_tools_output
from cpp_linter.cli import Args
from cpp_linter.common_fs.file_filter import FileFilter

TEST_REPO = "cpp-linter/test-cpp-linter-action"
TEST_PR = 27
DELETE_COMMENT_GRAPHQL = """{
  "data": {
    deletePullRequestReviewComment: {
      pullRequestReviewComment {
        %s
      }
    }
  }
}"""

RESOLVE_COMMENT_GRAPHQL = """{
  "data": {
    resolveReviewThread: {
      thread {
        %s
      }
    }
  }
}"""

MINIMIZE_COMMENT_GRAPHQL = """{
  "data": {
    "minimizeComment": {
      "minimizedComment": {
        "isMinimized": true
      }
    }
  }
}"""

CACHE_PATH = Path(__file__).parent


def graphql_callback(
    request: requests_mock.request._RequestObjectProxy,
    context: requests_mock.response._Context,
):
    context.status_code = 200
    req_json = request.json()
    query: str = req_json["query"]
    vars: Dict[str, Any] = req_json["variables"]
    if query.startswith("query"):
        # get existing review comments
        return (CACHE_PATH / "pr_reviews_graphql.json").read_text(encoding="utf-8")
    elif "resolveReviewThread" in query and "threadId" in vars:
        # resolve review
        return RESOLVE_COMMENT_GRAPHQL % vars["threadId"]
    elif "deletePullRequestReviewComment" in query and "id" in vars:
        # delete PR or minimizeComment
        return DELETE_COMMENT_GRAPHQL % vars["id"]
    elif "minimizeComment" in query:
        # minimizeComment
        return MINIMIZE_COMMENT_GRAPHQL
    else:  # pragma: no cover
        context.status_code = 403
        return json.dumps(
            {"errors": [{"message": "Failed to parse query when mocking a response"}]}
        )


test_parameters = OrderedDict(
    is_draft=False,
    is_closed=False,
    with_token=True,
    force_approved=False,
    tidy_review=False,
    format_review=True,
    changes=2,
    summary_only=False,
    no_lgtm=False,
    num_workers=None,
    is_passive=False,
    delete_review_comments=False,
)


def mk_param_set(**kwargs) -> OrderedDict:
    """Creates a dict of parameters values."""
    ret = test_parameters.copy()
    for key, value in kwargs.items():
        ret[key] = value
    return ret


@pytest.mark.parametrize(
    argnames=list(test_parameters.keys()),
    argvalues=[
        tuple(mk_param_set(is_draft=True).values()),
        tuple(mk_param_set(is_closed=True).values()),
        pytest.param(
            *tuple(mk_param_set(with_token=False).values()),
            marks=pytest.mark.xfail,
        ),
        tuple(mk_param_set(force_approved=True).values()),
        tuple(mk_param_set(force_approved=True, no_lgtm=True).values()),
        tuple(mk_param_set(tidy_review=True, format_review=False).values()),
        tuple(mk_param_set(tidy_review=True, format_review=True).values()),
        tuple(mk_param_set(format_review=True).values()),
        tuple(mk_param_set(tidy_review=True, changes=1).values()),
        tuple(mk_param_set(tidy_review=True, changes=0).values()),
        tuple(mk_param_set(tidy_review=True, changes=0, summary_only=True).values()),
        tuple(mk_param_set(is_passive=True).values()),
        tuple(mk_param_set(delete_review_comments=True).values()),
    ],
    ids=[
        "draft",
        "closed",
        "no_token",
        "approved",
        "no_lgtm",
        "tidy",  # changes == diff_chunks only
        "tidy+format",  # changes == diff_chunks only
        "format",  # changes == diff_chunks only
        "lines_added",
        "all_lines",
        "summary_only",
        "passive",
        "delete",
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
    num_workers: int,
    is_passive: bool,
    delete_review_comments: bool,
):
    """A mock test of posting PR reviews"""
    # patch env vars
    event_payload = {"number": TEST_PR}
    event_payload_path = tmp_path / "event_payload.json"
    event_payload_path.write_text(json.dumps(event_payload), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_payload_path))
    monkeypatch.setenv("CI", "true")
    if with_token:
        monkeypatch.setenv("GITHUB_TOKEN", "123456")
    if summary_only:
        monkeypatch.setenv("CPP_LINTER_PR_REVIEW_SUMMARY_ONLY", "true")
    monkeypatch.setenv("COVERAGE_FILE", str(Path.cwd() / ".coverage"))
    monkeypatch.chdir(str(tmp_path))
    (tmp_path / "src").mkdir()
    demo_dir = Path(__file__).parent.parent / "demo"
    shutil.copyfile(str(demo_dir / "demo.cpp"), str(tmp_path / "src" / "demo.cpp"))
    shutil.copyfile(str(demo_dir / "demo.hpp"), str(tmp_path / "src" / "demo.hpp"))
    shutil.copyfile(str(demo_dir / "demo.cpp"), str(tmp_path / "src" / "demo.c"))
    shutil.copyfile(
        str(CACHE_PATH / ".clang-format"), str(tmp_path / "src" / ".clang-format")
    )
    shutil.copyfile(
        str(CACHE_PATH / ".clang-tidy"), str(tmp_path / "src" / ".clang-tidy")
    )

    gh_client = GithubApiClient()
    gh_client.repo = TEST_REPO
    gh_client.event_name = "pull_request"

    with requests_mock.Mocker() as mock:
        base_url = f"{gh_client.api_url}/repos/{TEST_REPO}/pulls/{TEST_PR}"
        # load mock responses for pull_request event
        mock.get(
            base_url,
            request_headers={"Accept": "application/vnd.github.diff"},
            text=(CACHE_PATH / f"pr_{TEST_PR}.diff").read_text(encoding="utf-8"),
        )
        reviews = (CACHE_PATH / "pr_reviews.json").read_text(encoding="utf-8")
        mock.get(
            f"{base_url}/reviews?page=1&per_page=100",
            text=reviews,
        )
        mock.get(
            f"{base_url}/comments",
            text=(CACHE_PATH / "pr_review_comments.json").read_text(encoding="utf-8"),
        )

        # acknowledge any PUT and POST requests about specific reviews
        mock.post(f"{base_url}/reviews")
        for review_id in [r["id"] for r in json.loads(reviews) if "id" in r]:
            mock.put(f"{base_url}/reviews/{review_id}/dismissals")
        extensions = ["cpp", "hpp", "c"]

        # mock graphql requests
        graphql_url = f"{gh_client.api_url}/graphql"

        mock.post(graphql_url, text=graphql_callback)

        # run the actual test
        files = gh_client.get_list_of_changed_files(
            FileFilter(extensions=extensions),
            lines_changed_only=changes,
        )
        assert files
        for file_obj in files:
            assert file_obj.diff_chunks
        if force_approved:
            files.clear()

        args = Args()
        if not tidy_review:
            args.tidy_checks = "-*"
        args.version = environ.get("CLANG_VERSION", "16")
        args.style = "file"
        args.extensions = extensions
        args.ignore_tidy = "*.c"
        args.ignore_format = "*.c"
        args.lines_changed_only = changes
        args.tidy_review = tidy_review
        args.format_review = format_review
        args.jobs = num_workers
        args.thread_comments = "false"
        args.no_lgtm = no_lgtm
        args.file_annotations = False
        args.passive_reviews = is_passive
        args.delete_review_comments = delete_review_comments

        clang_versions = capture_clang_tools_output(files, args=args)
        if not force_approved:
            format_advice = list(filter(lambda x: x.format_advice is not None, files))
            tidy_advice = list(filter(lambda x: x.tidy_advice is not None, files))
            if tidy_review:
                assert tidy_advice and len(tidy_advice) <= len(files)
            else:
                assert not tidy_advice
            assert format_advice and len(format_advice) <= len(files)

        # simulate draft PR by changing the request response
        cache_pr_response = (CACHE_PATH / f"pr_{TEST_PR}.json").read_text(
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
        gh_client.post_feedback(files, args, clang_versions)

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
            if is_passive:
                assert json_payload["event"] == "COMMENT"
            else:
                if force_approved:
                    assert json_payload["event"] == "APPROVE"
                else:
                    assert json_payload["event"] == "REQUEST_CHANGES"

            # save the body of the review json for manual inspection
            assert hasattr(last_request, "text")
            (tmp_path / "review.json").write_text(
                json.dumps(json_payload, indent=2), encoding="utf-8"
            )
