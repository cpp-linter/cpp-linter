"""Tests for checking the :std:option:`--repo-root` path."""

from pathlib import Path

import pytest

import cpp_linter
from cpp_linter.cli import Args
from cpp_linter.common_fs import change_to_repo_root


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
    change_to_repo_root(repo_root)
    assert Path.cwd().samefile(work / expected)


@pytest.mark.no_clang
def test_absolute_inside_cwd(work: Path):
    change_to_repo_root(str(work / "sub"))
    assert Path.cwd().samefile(work / "sub")


@pytest.mark.no_clang
@pytest.mark.parametrize("repo_root", ["..", "sub/../..", "../work-other"])
def test_outside_cwd(work: Path, repo_root: str):
    with pytest.raises(ValueError, match="is outside the working directory"):
        change_to_repo_root(repo_root)
    assert Path.cwd().samefile(work)


@pytest.mark.no_clang
def test_absolute_outside_cwd(work: Path):
    with pytest.raises(ValueError, match="is outside the working directory"):
        change_to_repo_root(str(work.parent / "work-other"))
    assert Path.cwd().samefile(work)


@pytest.mark.no_clang
def test_symlink_outside_cwd(work: Path):
    link = work / "link"
    try:
        link.symlink_to(work.parent / "work-other", target_is_directory=True)
    except OSError:  # pragma: no cover
        pytest.skip("cannot create symbolic links here")
    with pytest.raises(ValueError, match="is outside the working directory"):
        change_to_repo_root("link")
    assert Path.cwd().samefile(work)


@pytest.mark.no_clang
@pytest.mark.parametrize("repo_root", ["file.txt", "missing"])
def test_not_a_directory(work: Path, repo_root: str):
    with pytest.raises(ValueError, match="is not a directory"):
        change_to_repo_root(repo_root)
    assert Path.cwd().samefile(work)


@pytest.mark.no_clang
def test_main_rejects_outside_repo_root(
    work: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """cpp-linter stops with an error instead of changing to the given directory."""
    args = Args()
    args.repo_root = ".."

    class Parser:
        def parse_args(self, **kwargs):
            return args

    class Client:
        event_name = "push"
        client_kind = "local"
        is_pr_event = False
        debug_enabled = False

    monkeypatch.setattr(cpp_linter, "get_cli_parser", lambda: Parser())
    monkeypatch.setattr(cpp_linter, "LinterClient", lambda: Client())

    with pytest.raises(SystemExit) as exc:
        cpp_linter.main()
    assert exc.value.code == 1
    assert "--repo-root '..' is outside the working directory" in caplog.text
    assert Path.cwd().samefile(work)
