"""Tests for checking the :std:option:`--repo-root` path."""

import asyncio
import logging
import os
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import git_bot_feedback as gbf
import pytest

import cpp_linter
from cpp_linter import rest_api
from cpp_linter.clang_tools.clang_format import FormatAdvice
from cpp_linter.clang_tools.clang_tidy import TidyAdvice
from cpp_linter.clang_tools.patcher import Suggestion
from cpp_linter.clang_versions import ClangVersions
from cpp_linter.cli import Args
from cpp_linter.common_fs import FileObj, get_repo_root_prefix, resolve_repo_root
from cpp_linter.common_fs.file_filter import make_file_filter
from cpp_linter.git import get_list_of_changed_files
from cpp_linter.rest_api import LinterClient, make_annotations


@pytest.fixture
def work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A working directory with a sub-directory, a file, and a sibling directory
    whose name starts with the working directory's name."""
    work = tmp_path / "work"
    (work / "sub").mkdir(parents=True)
    (work / "file.txt").touch()
    (tmp_path / "work-other").mkdir()
    monkeypatch.chdir(work)
    return work


@pytest.mark.no_clang
@pytest.mark.parametrize(
    "repo_root,expected",
    [(".", "."), ("", "."), ("sub", "sub"), ("sub/", "sub"), ("sub/..", ".")],
)
def test_inside_cwd(work: Path, repo_root: str, expected: str):
    assert resolve_repo_root(repo_root) == os.path.realpath(work / expected)


@pytest.mark.no_clang
def test_absolute_inside_cwd(work: Path):
    assert resolve_repo_root(str(work / "sub")) == os.path.realpath(work / "sub")


@pytest.mark.no_clang
@pytest.mark.parametrize("repo_root", ["..", "sub/../..", "../work-other"])
def test_outside_cwd(work: Path, repo_root: str):
    with pytest.raises(ValueError, match="is outside the working directory"):
        resolve_repo_root(repo_root)


@pytest.mark.no_clang
def test_absolute_outside_cwd(work: Path):
    with pytest.raises(ValueError, match="is outside the working directory"):
        resolve_repo_root(str(work.parent / "work-other"))


@pytest.mark.no_clang
def test_symlink_outside_cwd(work: Path):
    link = work / "link"
    try:
        link.symlink_to(work.parent / "work-other", target_is_directory=True)
    except OSError:  # pragma: no cover
        pytest.skip("cannot create symbolic links here")
    with pytest.raises(ValueError, match="is outside the working directory"):
        resolve_repo_root("link")


@pytest.mark.no_clang
@pytest.mark.parametrize("repo_root", ["file.txt", "missing"])
def test_not_a_directory(work: Path, repo_root: str):
    with pytest.raises(ValueError, match="is not a directory"):
        resolve_repo_root(repo_root)


@pytest.mark.no_clang
def test_main_rejects_outside_repo_root(
    work: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """cpp-linter stops with an error before it reads anything from the path."""
    args = Args()
    args.repo_root = ".."

    class Client:
        event_name = "push"
        client_kind = "local"
        is_pr_event = False
        debug_enabled = False

    parser = type("Parser", (), {"parse_args": lambda *_, **__: args})()
    monkeypatch.setattr(cpp_linter, "get_cli_parser", lambda: parser)
    monkeypatch.setattr(cpp_linter, "LinterClient", Client)

    with pytest.raises(SystemExit) as exc:
        cpp_linter.main()
    assert exc.value.code == 1
    assert "--repo-root '..' is outside the working directory" in caplog.text


@pytest.fixture
def mono_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A git repository whose ``member`` folder is used as the repo root, while
    cpp-linter runs from the top level of the git repository."""
    repo = tmp_path / "mono"
    (repo / ".git").mkdir(parents=True)
    (repo / "member" / "src").mkdir(parents=True)
    monkeypatch.chdir(repo)
    return repo


@pytest.mark.no_clang
@pytest.mark.parametrize(
    "repo_root,expected",
    [(".", ""), ("member", "member/"), ("member/src", "member/src/")],
)
def test_repo_root_prefix(mono_repo: Path, repo_root: str, expected: str):
    assert get_repo_root_prefix(repo_root) == expected


@pytest.mark.no_clang
def test_repo_root_prefix_in_nested_repo(mono_repo: Path):
    """A submodule has a ``.git`` file, and is its own git repository."""
    (mono_repo / "member" / ".git").touch()
    assert get_repo_root_prefix("member") == ""
    assert get_repo_root_prefix("member/src") == "src/"


@pytest.mark.no_clang
def test_repo_root_prefix_in_sub_folder(
    mono_repo: Path, monkeypatch: pytest.MonkeyPatch
):
    """The working directory can be a sub-folder of the git repository."""
    monkeypatch.chdir(mono_repo / "member")
    assert get_repo_root_prefix(".") == "member/"
    assert get_repo_root_prefix("src") == "member/src/"


@pytest.mark.no_clang
def test_repo_root_prefix_without_git(work: Path):
    """Without a ``.git`` folder (a checkout made without git), the working directory
    is used as the top level of the repository."""
    assert get_repo_root_prefix(".") == ""
    assert get_repo_root_prefix("sub") == "sub/"


@pytest.mark.no_clang
def test_repo_root_prefix_from_workspace_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Without a ``.git`` folder, the CI workspace is the top level of the repository,
    even when cpp-linter runs from a sub-folder of it."""
    workspace = tmp_path / "workspace"
    (workspace / "member" / "src").mkdir(parents=True)
    monkeypatch.chdir(workspace / "member")
    assert get_repo_root_prefix(".", workspace) == "member/"
    assert get_repo_root_prefix("src", workspace) == "member/src/"


@pytest.mark.no_clang
def test_repo_root_prefix_prefers_git_root(mono_repo: Path, tmp_path: Path):
    """A ``.git`` folder wins over the CI workspace, as with ``actions/checkout``
    ``path: mono``, where ``GITHUB_WORKSPACE`` is the parent of the git repository."""
    assert get_repo_root_prefix("member", tmp_path) == "member/"


@pytest.mark.no_clang
def test_repo_root_prefix_ignores_unrelated_workspace_root(work: Path, tmp_path: Path):
    """A workspace root that does not contain the repo root is not used."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    assert get_repo_root_prefix("sub", elsewhere) == "sub/"


class FakeWorkspaceClient:
    def __init__(self, workspace_root: Path | None, error: str | None = None):
        self._workspace_root = workspace_root
        self._error = error

    def workspace_root(self) -> Path | None:
        if self._error is not None:
            raise ValueError(self._error)
        return self._workspace_root


@pytest.mark.no_clang
def test_client_workspace_root(tmp_path: Path):
    client = LinterClient(cast(gbf.GitClient, FakeWorkspaceClient(tmp_path)))
    assert client.workspace_root() == tmp_path
    client = LinterClient(cast(gbf.GitClient, FakeWorkspaceClient(None)))
    assert client.workspace_root() is None


@pytest.mark.no_clang
def test_client_workspace_root_error(caplog: pytest.LogCaptureFixture):
    """An unreadable workspace variable is logged and treated as no workspace."""
    client = LinterClient(
        cast(gbf.GitClient, FakeWorkspaceClient(None, "GITHUB_WORKSPACE is not set"))
    )
    with caplog.at_level(logging.WARNING, logger="CPP Linter"):
        assert client.workspace_root() is None
    assert "GITHUB_WORKSPACE is not set" in caplog.text


class ChangedFilesClient:
    """Lists the given changed files that pass the file filter, like git-bot-feedback.

    The file names are relative to the top level of the git repository."""

    def __init__(self, names: list[str]):
        self.names = names
        self.file_filter: gbf.FileFilter | None = None

    async def get_list_of_changed_files(
        self,
        file_filter: gbf.FileFilter,
        lines_changed_only: gbf.LinesChangedOnly,
        base_diff: str | None = None,
        ignore_index: bool = False,
    ):
        self.file_filter = file_filter
        return {
            name: SimpleNamespace(diff_hunks=[(1, 3)], added_lines=[2])
            for name in self.names
            if file_filter.is_qualified(name)
        }


@pytest.mark.no_clang
def test_changed_files_relative_to_repo_root(mono_repo: Path):
    """Changed files are named relative to the repo root. The file filter applies to
    those names, and changed files outside the repo root are left out."""
    git_client = ChangedFilesClient(
        [
            "member/src/a.cpp",
            "member/src/gen.cpp",  # ignored
            "member/src/notes.txt",  # not a source file
            "other/b.cpp",  # outside the repo root
        ]
    )
    files = asyncio.run(
        get_list_of_changed_files(
            git_client=cast(gbf.GitClient, git_client),
            file_filter=make_file_filter(
                ignore_value="src/gen.cpp", extensions=["cpp"]
            ),
            lines_changed_only=0,
            path_prefix="member/",
        )
    )
    assert [f.name for f in files] == ["src/a.cpp"]
    assert files[0].diff_chunks == [[1, 3]]
    assert files[0].additions == [2]


@pytest.mark.no_clang
def test_changed_files_at_top_level(mono_repo: Path):
    """At the top level of the git repository, the names and the filter are used as
    they are."""
    git_client = ChangedFilesClient(["member/src/a.cpp", "member/build/gen.cpp"])
    file_filter = make_file_filter(
        ignore_value="member/build/gen.cpp", extensions=["cpp"]
    )
    files = asyncio.run(
        get_list_of_changed_files(
            git_client=cast(gbf.GitClient, git_client),
            file_filter=file_filter,
            lines_changed_only=0,
        )
    )
    assert git_client.file_filter is file_filter
    assert [f.name for f in files] == ["member/src/a.cpp"]


@pytest.mark.no_clang
def test_annotations_use_git_paths(mono_repo: Path):
    """Annotations name files relative to the git repository."""
    file_obj = FileObj("src/a.cpp")
    file_obj.format_advice = cast(
        FormatAdvice, SimpleNamespace(replaced_lines=[SimpleNamespace(line=1)])
    )
    file_obj.tidy_advice = cast(
        TidyAdvice,
        SimpleNamespace(
            notes=[
                SimpleNamespace(
                    filename="src/a.cpp",
                    severity="warning",
                    line="2",
                    cols="1",
                    diagnostic="check-name",
                    rationale="a concern",
                )
            ]
        ),
    )
    annotations = make_annotations([file_obj], "llvm", "member/")
    assert [a.path for a in annotations] == ["member/src/a.cpp"] * 2


@pytest.mark.no_clang
def test_review_comments_use_git_paths(
    mono_repo: Path, monkeypatch: pytest.MonkeyPatch
):
    """Review comments name files relative to the git repository."""

    def fake_create_review_comments(files, is_tidy, summary_only, review, repo_root):
        suggestion = Suggestion("src/a.cpp")
        suggestion.line_end = 2
        suggestion.comment = "### clang-format\nformat issue"
        review.suggestions.append(suggestion)
        review.tool_total["clang-format"] = 1

    class ReviewClient:
        paths: list[str] = []

        async def cull_pr_reviews(self, options):
            self.paths = [comment.path for comment in options.comments]
            options.comments = []  # stop before posting a review
            return options

    monkeypatch.setattr(rest_api, "create_review_comments", fake_create_review_comments)
    git_client = ReviewClient()
    client = LinterClient(cast(gbf.GitClient, git_client))
    client.repo_root_prefix = "member/"
    args = Args()
    args.format_review = True
    args.repo_root = str(mono_repo / "member")
    asyncio.run(client._post_review([FileObj("src/a.cpp")], args, ClangVersions()))
    assert git_client.paths == ["member/src/a.cpp"]
