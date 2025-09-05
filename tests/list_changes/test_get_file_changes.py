import json
import logging
from pathlib import Path
import pytest
import requests_mock
from cpp_linter import GithubApiClient, logger, FileFilter
import cpp_linter.rest_api.github_api
from cpp_linter._version import version


TEST_PR = 27
TEST_REPO = "cpp-linter/test-cpp-linter-action"
TEST_SHA = "708a1371f3a966a479b77f1f94ec3b7911dffd77"
TEST_API_URL = "https://api.mock.com"
TEST_ASSETS = Path(__file__).parent
TEST_DIFF = (TEST_ASSETS / "patch.diff").read_text(encoding="utf-8")


@pytest.mark.no_clang
@pytest.mark.parametrize(
    "event_name,paginated,fake_runner,lines_changed_only",
    [
        # push event (full diff)
        (
            "unknown",  # let coverage include logged warning about unknown event
            False,
            True,
            1,
        ),
        # pull request event (full diff)
        (
            "pull_request",
            False,
            True,
            1,
        ),
        # push event (paginated diff)
        (
            "push",  # let coverage include logged warning about unknown event
            True,
            True,
            1,
        ),
        # pull request event (paginated diff)
        (
            "pull_request",
            True,
            True,
            1,
        ),
        # push event (paginated diff with all lines)
        (
            "push",  # let coverage include logged warning about unknown event
            True,
            True,
            0,
        ),
        # pull request event (paginated diff with all lines)
        (
            "pull_request",
            True,
            True,
            0,
        ),
        # local dev env
        ("", False, False, 1),
    ],
    ids=[
        "push",
        "pull_request",
        "push(paginated)",
        "pull_request(paginated)",
        "push(all-lines,paginated)",
        "pull_request(all-lines,paginated)",
        "local_dev",
    ],
)
def test_get_changed_files(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    event_name: str,
    paginated: bool,
    fake_runner: bool,
    lines_changed_only: int,
):
    """test getting a list of changed files for an event."""
    caplog.set_level(logging.DEBUG, logger=logger.name)

    # setup test to act as though executed in user's repo's CI
    event_payload = {"number": TEST_PR}
    event_payload_path = tmp_path / "event_payload.json"
    event_payload_path.write_text(json.dumps(event_payload), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_payload_path))
    monkeypatch.setenv("GITHUB_EVENT_NAME", event_name)
    monkeypatch.setenv("GITHUB_REPOSITORY", TEST_REPO)
    monkeypatch.setenv("GITHUB_SHA", TEST_SHA)
    monkeypatch.setenv("GITHUB_API_URL", TEST_API_URL)
    monkeypatch.setenv("CI", str(fake_runner).lower())
    monkeypatch.setenv("GITHUB_TOKEN", "123456")
    gh_client = GithubApiClient()

    if not fake_runner:
        # getting a diff in CI (on a shallow checkout) fails
        # monkey patch the .git.get_diff() to return the test's diff asset
        monkeypatch.setattr(
            cpp_linter.rest_api.github_api,
            "get_diff",
            lambda *args: TEST_DIFF,
        )

    endpoint = f"{TEST_API_URL}/repos/{TEST_REPO}/commits/{TEST_SHA}"
    if event_name == "pull_request":
        endpoint = f"{TEST_API_URL}/repos/{TEST_REPO}/pulls/{TEST_PR}"

    with requests_mock.Mocker() as mock:
        mock.get(
            endpoint,
            request_headers={
                "Authorization": "token 123456",
                "Accept": "application/vnd.github.diff",
                "User-Agent": f"cpp-linter/{version}",
            },
            text=TEST_DIFF if not paginated else "",
            status_code=200 if not paginated else 403,
        )

        if paginated:
            mock_endpoint = endpoint
            if event_name == "pull_request":
                mock_endpoint += "/files"
            logger.debug("mock endpoint: %s", mock_endpoint)
            for pg in (1, 2):
                response_asset = f"{event_name}_files_pg{pg}.json"
                mock.get(
                    mock_endpoint + ("" if pg == 1 else "?page=2"),
                    request_headers={
                        "Authorization": "token 123456",
                        "Accept": "application/vnd.github.raw+json",
                        "User-Agent": f"cpp-linter/{version}",
                    },
                    headers={"link": f'<{mock_endpoint}?page=2>; rel="next"'}
                    if pg == 1
                    else {},
                    text=(TEST_ASSETS / response_asset).read_text(encoding="utf-8"),
                )

        files = gh_client.get_list_of_changed_files(
            FileFilter(extensions=["cpp", "hpp"]), lines_changed_only=lines_changed_only
        )
        assert files
        for file in files:
            expected = ["src/demo.cpp", "src/demo.hpp"]
            if lines_changed_only == 0:
                expected.append("include/test/tree.hpp")
            assert file.name in expected
