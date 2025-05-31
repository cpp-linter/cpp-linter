import time
from typing import Dict
import requests_mock
import pytest

from cpp_linter.rest_api.github_api import GithubApiClient

TEST_REPO = "test-user/test-repo"
TEST_SHA = "0123456789ABCDEF"
BASE_HEADERS = {
    "x-ratelimit-remaining": "1",
    "x-ratelimit-reset": str(int(time.mktime(time.localtime(None)))),
}


@pytest.mark.no_clang
@pytest.mark.parametrize(
    "response_headers",
    [
        {**BASE_HEADERS, "x-ratelimit-remaining": "0"},
        {**BASE_HEADERS, "retry-after": "0.1"},
    ],
    ids=["primary", "secondary"],
)
def test_rate_limit(monkeypatch: pytest.MonkeyPatch, response_headers: Dict[str, str]):
    """A mock test for hitting Github REST API rate limits"""
    # patch env vars
    monkeypatch.setenv("GITHUB_TOKEN", "123456")
    monkeypatch.setenv("GITHUB_REPOSITORY", TEST_REPO)
    monkeypatch.setenv("GITHUB_SHA", TEST_SHA)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_EVENT_PATH", "")

    gh_client = GithubApiClient()

    with requests_mock.Mocker() as mock:
        url = f"{gh_client.api_url}/repos/{TEST_REPO}/commits/{TEST_SHA}"

        # load mock responses for push event
        mock.get(url, status_code=403, headers=response_headers)

        # ensure function exits early
        with pytest.raises(SystemExit) as exc:
            gh_client.api_request(url)
        assert exc.type is SystemExit
        assert exc.value.code == 1
