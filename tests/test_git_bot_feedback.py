import asyncio

import git_bot_feedback as gbf
import pytest

from cpp_linter.clang_tools import ClangVersions
from cpp_linter.cli import Args
from cpp_linter.common_fs import FileObj
from cpp_linter.common_fs.file_filter import make_file_filter
from cpp_linter.git import (
    get_list_of_changed_files,
    to_gbf_lines_changed_only,
)
from cpp_linter.rest_api import LinterClient


@pytest.mark.no_clang
def test_to_gbf_converters():
    assert to_gbf_lines_changed_only(0) == gbf.LinesChangedOnly.Off
    assert to_gbf_lines_changed_only(1) == gbf.LinesChangedOnly.Diff
    assert to_gbf_lines_changed_only(2) == gbf.LinesChangedOnly.On
    assert to_gbf_lines_changed_only(gbf.LinesChangedOnly.On) == gbf.LinesChangedOnly.On


@pytest.mark.no_clang
def test_get_list_of_changed_files_local(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    client = gbf.GitClient()
    assert client.client_kind == "local"
    files = asyncio.run(
        get_list_of_changed_files(
            git_client=client,
            file_filter=make_file_filter(extensions=["toml", "py", "rst"]),
            lines_changed_only=0,
        )
    )
    assert isinstance(files, list)


@pytest.mark.no_clang
def test_post_feedback_local_client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    client = LinterClient()
    args = Args()
    args.step_summary = True
    args.file_annotations = True
    args.thread_comments = "false"
    args.lines_changed_only = 0
    args.summary_output_file = str(tmp_path / "summary.md")

    files = [FileObj("src/main.cpp")]
    clang_versions = ClangVersions()
    clang_versions.tidy = "18.0.0"
    clang_versions.format = "18.0.0"

    # Should run cleanly with local client without exceptions
    asyncio.run(client.post_feedback(files, args, clang_versions))

    assert (tmp_path / "summary.md").exists()
    summary_content = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "Cpp-Linter Report" in summary_content
