import json
from pathlib import Path
import time
from typing import Dict
import requests_mock
import pytest

from cpp_linter.rest_api.github_api import GithubApiClient

DUMMY_RESPONSE = {
    "message": "DUMMY response for rate limit violations",
    "documentation_url": (
        "https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api",
    ),
}
TEST_REPO = "test-user/test-repo"
TEST_SHA = "0123456789ABCDEF"
BASE_HEADERS = {
    "x-ratelimit-remaining": "1",
    "x-ratelimit-reset": str(int(time.mktime(time.localtime(None)))),
}


@pytest.mark.parametrize(
    "response_headers",
    [
        {**BASE_HEADERS, "x-ratelimit-remaining": "0"},
        {**BASE_HEADERS, "retry-after": "0.25"},
    ],
    ids=["primary", "secondary"],
)
def test_post_feedback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    response_headers: Dict[str, str],
):
    """A mock test of posting comments and step summary"""
    # patch env vars
    event_payload = {"repository": {"private": False}}
    event_payload_path = tmp_path / "event_payload.json"
    event_payload_path.write_text(json.dumps(event_payload), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_payload_path))
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("GITHUB_TOKEN", "123456")
    monkeypatch.setenv("GITHUB_REPOSITORY", TEST_REPO)
    monkeypatch.setenv("GITHUB_SHA", TEST_SHA)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_EVENT_PATH", "")

    gh_client = GithubApiClient()

    with requests_mock.Mocker() as mock:
        url = f"{gh_client.api_url}/repos/{TEST_REPO}/commits/{TEST_SHA}"

        # load mock responses for push event
        mock.get(
            url,
            status_code=403,
            text=json.dumps(DUMMY_RESPONSE),
            headers=response_headers,
        )

        response = gh_client.api_request(url)
        assert response is None
