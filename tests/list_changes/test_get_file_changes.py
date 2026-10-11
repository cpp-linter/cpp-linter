import asyncio
import json
from pathlib import Path

import pytest
from mock_server import MockServer

from cpp_linter.common_fs.file_filter import make_file_filter
from cpp_linter.rest_api import LinterClient

TEST_PR = 27
TEST_REPO = "cpp-linter/test-cpp-linter-action"
TEST_SHA = "708a1371f3a966a479b77f1f94ec3b7911dffd77"
TEST_ASSETS = Path(__file__).parent


def _setup_event(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, event_name: str
) -> None:
    payload: dict[str, object] = {"number": TEST_PR}
    if event_name == "pull_request":
        payload["pull_request"] = {
            "number": TEST_PR,
            "draft": False,
            "state": "open",
            "locked": False,
        }
    event_path = tmp_path / "event_payload.json"
    event_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_EVENT_NAME", event_name)
    monkeypatch.setenv("GITHUB_REPOSITORY", TEST_REPO)
    monkeypatch.setenv("GITHUB_SHA", TEST_SHA)
    monkeypatch.setenv("GITHUB_TOKEN", "123456")


def _endpoint(event_name: str) -> str:
    if event_name == "pull_request":
        return f"/repos/{TEST_REPO}/pulls/{TEST_PR}/files"
    return f"/repos/{TEST_REPO}/commits/{TEST_SHA}"


@pytest.mark.no_clang
@pytest.mark.parametrize("event_name", ["push", "pull_request"])
@pytest.mark.parametrize("lines_changed_only", [0, 1])
def test_get_changed_files(
    mock_server: MockServer,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    event_name: str,
    lines_changed_only: int,
):
    """test getting a (paginated) list of changed files for an event."""
    _setup_event(monkeypatch, tmp_path, event_name)
    endpoint = _endpoint(event_name)
    pages = [
        (TEST_ASSETS / f"{event_name}_files_pg{pg}.json").read_text(encoding="utf-8")
        for pg in (1, 2)
    ]
    mock_server.get(
        endpoint,
        text=pages[0],
        headers={"link": f'<{{base_url}}{endpoint}?page=2>; rel="next"'},
    )
    mock_server.get(endpoint, text=pages[1], query="page=2")

    client = LinterClient()
    files = asyncio.run(
        client.get_changed_files(
            make_file_filter(extensions=["cpp", "hpp"]),
            lines_changed_only=lines_changed_only,
        )
    )
    expected = ["src/demo.cpp", "src/demo.hpp"]
    if lines_changed_only == 0:
        expected.append("include/test/tree.hpp")
    assert files
    assert sorted(file.name for file in files) == sorted(expected)


@pytest.mark.no_clang
@pytest.mark.parametrize("event_name", ["pull_request", "push"])
@pytest.mark.parametrize("status", ["added", "modified", "renamed", "removed"])
@pytest.mark.parametrize("lines_changed_only", [0, 1, 2])
def test_files_without_patches(
    mock_server: MockServer,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    event_name: str,
    status: str,
    lines_changed_only: int,
):
    """Missing patches permit whole-file linting, but not line filtering."""
    _setup_event(monkeypatch, tmp_path, event_name)
    entries = [
        {
            "filename": "src/deleted.cpp",
            "status": "removed",
            "changes": 1,
            "patch": "@@ -1 +0,0 @@\n-int removed;",
        },
        {"filename": "src/large.cpp", "status": status, "changes": 1000},
    ]
    mock_server.get(
        _endpoint(event_name),
        text=json.dumps(
            entries if event_name == "pull_request" else {"files": entries}
        ),
    )
    client = LinterClient()
    files = asyncio.run(
        client.get_changed_files(
            make_file_filter(extensions=["cpp"]), lines_changed_only=lines_changed_only
        )
    )
    # git-bot-feedback skips files lacking patch info when filtering by lines
    skipped = status == "removed" or lines_changed_only > 0
    assert [file.name for file in files] == ([] if skipped else ["src/large.cpp"])
