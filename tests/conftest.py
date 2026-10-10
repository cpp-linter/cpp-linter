from collections.abc import Iterator

import pytest
from mock_server import MockServer, start_mock_server


@pytest.fixture
def mock_server(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[MockServer]:
    """A local server that ``GITHUB_API_URL`` is pointed at."""
    server, httpd = start_mock_server()
    out_dir = tmp_path_factory.mktemp("gh_files")
    for name in ("output", "step_summary.md"):
        (out_dir / name).touch()
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_OUTPUT", str(out_dir / "output"))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(out_dir / "step_summary.md"))
    monkeypatch.setenv("GITHUB_API_URL", server.base_url)
    monkeypatch.setenv("GITHUB_SERVER_URL", server.base_url)
    monkeypatch.setenv("GITHUB_RUN_ID", "42024")
    yield server
    httpd.shutdown()
    httpd.server_close()
