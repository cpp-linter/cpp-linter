"""Tests for the diff that PR review suggestions are built from."""

import pytest

from cpp_linter.clang_tools.patcher import Patch


def lines(patch: Patch) -> list[list[tuple[str, str, int]]]:
    return [
        [(line.origin, line.content, line.old_lineno) for line in hunk.lines]
        for hunk in patch.hunks
    ]


def test_no_changes():
    patch = Patch.create_from(b"a\nb\n", b"a\nb\n", "x.cpp")
    assert patch.text == ""
    assert patch.hunks == []


def test_hunks_and_text():
    patch = Patch.create_from(b"a\nb\nc\nd\n", b"a\nB\nc\nd\ne\n", "src/x.cpp")
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


def test_removal_only():
    patch = Patch.create_from(b"a\nb\nc\n", b"a\nc\n", "x.cpp")
    assert lines(patch) == [[("-", "b\n", 2)]]


@pytest.mark.parametrize(
    "old,new,expected",
    [
        # line endings are compared as-is, whatever the repo's .gitattributes says
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
def test_line_content(old: bytes, new: bytes, expected: list):
    assert lines(Patch.create_from(old, new, "x.cpp")) == [expected]


def test_git_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("cpp_linter.clang_tools.patcher.shutil.which", lambda _: None)
    with pytest.raises(FileNotFoundError):
        Patch.create_from(b"a\n", b"b\n", "x.cpp")
