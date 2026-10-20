"""Tests for the diff that PR review suggestions are built from."""

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from cpp_linter.clang_tools.patcher import Patch

DiffFn = Callable[..., Patch]


@pytest.fixture
def diff(tmp_path: Path) -> DiffFn:
    """Write ``old`` to a file and diff it against ``new``."""

    def _diff(old: bytes, new: bytes, file_name: str = "x.cpp") -> Patch:
        old_path = tmp_path / file_name
        old_path.parent.mkdir(parents=True, exist_ok=True)
        old_path.write_bytes(old)
        return Patch.create_from(old_path, new, file_name)

    return _diff


def lines(patch: Patch) -> list[list[tuple[str, str, int]]]:
    return [
        [(line.origin, line.content, line.old_lineno) for line in hunk.lines]
        for hunk in patch.hunks
    ]


def test_no_changes(diff: DiffFn):
    patch = diff(b"a\nb\n", b"a\nb\n")
    assert patch.text == ""
    assert patch.hunks == []


def test_hunks_and_text(diff: DiffFn):
    patch = diff(b"a\nb\nc\nd\n", b"a\nB\nc\nd\ne\n", "src/x.cpp")
    assert lines(patch) == [
        [("-", "b\n", 2), ("+", "B\n", -1)],
        [("+", "e\n", -1)],
    ]
    first, second = patch.hunks
    assert (first.old_start, first.old_lines, first.new_start, first.new_lines) == (
        2,
        1,
        2,
        1,
    )
    assert (second.old_start, second.old_lines) == (4, 0)
    assert patch.text.startswith(
        "diff --git a/src/x.cpp b/src/x.cpp\n--- a/src/x.cpp\n+++ b/src/x.cpp\n@@ -2 +2 @@"
    )


def test_removal_only(diff: DiffFn):
    patch = diff(b"a\nb\nc\n", b"a\nc\n")
    assert lines(patch) == [[("-", "b\n", 2)]]


@pytest.mark.parametrize(
    "old,new,expected",
    [
        # line endings are compared as-is
        (
            b"x\r\ny\r\n",
            b"x\ny\n",
            [("-", "x\r\n", 1), ("-", "y\r\n", 2), ("+", "x\n", -1), ("+", "y\n", -1)],
        ),
        # a form feed is part of the line, not a line break
        (b"\x0c\nq\n", b"\nq\n", [("-", "\x0c\n", 1), ("+", "\n", -1)]),
        # missing newline at end of file
        (b"a\nb", b"a\nb\n", [("-", "b", 2), ("+", "b\n", -1)]),
    ],
)
def test_line_content(diff: DiffFn, old: bytes, new: bytes, expected: list):
    assert lines(diff(old, new)) == [expected]


def test_repo_gitattributes_ignored(tmp_path: Path, diff: DiffFn):
    """The user's `.gitattributes` must not hide CRLF -> LF fixes."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitattributes").write_text("* text=auto\n")
    assert lines(diff(b"x\r\n", b"x\n")) == [[("-", "x\r\n", 1), ("+", "x\n", -1)]]


def test_symlink(tmp_path: Path):
    target = tmp_path / "real.cpp"
    target.write_bytes(b"a\n")
    link = tmp_path / "link.cpp"
    try:
        link.symlink_to(target)
    except OSError:  # pragma: no cover
        pytest.skip("symlinks are not supported here")
    patch = Patch.create_from(link, b"b\n", "link.cpp")
    assert lines(patch) == [[("-", "a\n", 1), ("+", "b\n", -1)]]


def test_git_missing(monkeypatch: pytest.MonkeyPatch, diff: DiffFn):
    monkeypatch.setattr("cpp_linter.clang_tools.patcher.shutil.which", lambda _: None)
    with pytest.raises(FileNotFoundError):
        diff(b"a\n", b"b\n")


def test_inherited_git_config_ignored(monkeypatch: pytest.MonkeyPatch, diff: DiffFn):
    # myers and patience give different hunks for these
    old, new = b"b\na\n{\na\n}\n}\n", b"}\n}\nb\na\n}\na\n"
    expected = lines(diff(old, new))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "diff.algorithm")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "patience")
    assert lines(diff(old, new)) == expected


def test_git_error(tmp_path: Path):
    with pytest.raises(RuntimeError, match="git diff failed for missing.cpp"):
        Patch.create_from(tmp_path / "missing.cpp", b"a\n", "missing.cpp")
