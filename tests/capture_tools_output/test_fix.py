"""Tests for the ``--fix`` option that auto-applies clang-format fixes in place."""

import os
from pathlib import Path
import shutil

import pytest

from cpp_linter.common_fs import FileObj
from cpp_linter.clang_tools import capture_clang_tools_output
from cpp_linter.clang_tools.clang_format import tally_format_advice
from cpp_linter.clang_tools.patcher import ReviewComments
from cpp_linter.cli import Args

CLANG_VERSION = os.getenv("CLANG_VERSION", "16")


def _fix_args(style: str) -> Args:
    args = Args()
    args.tidy_checks = "-*"  # disable clang-tidy
    args.version = CLANG_VERSION
    args.style = style
    args.extensions = ["c", "h", "cpp", "hpp"]
    args.fix = True
    return args


@pytest.mark.parametrize("style", ["llvm", "file"])
def test_fix_applies_clang_format(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    style: str,
):
    """``--fix`` reformats a malformed file in place and clears its advice."""
    monkeypatch.setenv("COVERAGE_FILE", str(Path.cwd() / ".coverage"))

    # Work on a copy of the intentionally ugly demo sources so the repo's
    # originals stay untouched. The demo dir ships a .clang-format used by the
    # ``file`` style.
    demo_dir = Path(__file__).parent.parent / "demo"
    shutil.copytree(str(demo_dir), str(tmp_path / "demo"))
    monkeypatch.chdir(str(tmp_path))

    demo_file = "demo/demo.cpp"
    original = Path(demo_file).read_text(encoding="utf-8")

    files = [FileObj(demo_file)]
    capture_clang_tools_output(files, args=_fix_args(style))

    # The ugly demo had format issues, so --fix must have rewritten the file...
    formatted = Path(demo_file).read_text(encoding="utf-8")
    assert formatted != original
    # ...and reset the advice so nothing is still reported as unformatted.
    assert tally_format_advice(files) == 0

    # A second pass is a no-op: the file is already formatted, so the fix loop
    # skips it (covers the "nothing to fix" branch).
    files_again = [FileObj(demo_file)]
    capture_clang_tools_output(files_again, args=_fix_args(style))
    assert Path(demo_file).read_text(encoding="utf-8") == formatted
    assert tally_format_advice(files_again) == 0


# A file whose formatting changes its line count: the one-liner below expands
# into several lines, pushing every later diagnostic down.
_SHIFTING_SRC = """\
void chain() { int q = 1; int w = 2; int e = 3; int r = 4; int t = 5; }

int magic() {
  int v = 42;
  return v;
}

int *ptr_thing() {
  int *p = 0;
  return p;
}
"""

_TIDY_ORDER_CHECKS = "-*,readability-magic-numbers,modernize-use-nullptr"


def _tidy_order_args(fix: bool) -> Args:
    args = Args()
    args.tidy_checks = _TIDY_ORDER_CHECKS
    args.version = CLANG_VERSION
    args.style = "llvm"
    args.extensions = ["c", "h", "cpp", "hpp"]
    args.lines_changed_only = 1
    args.extra_arg = ["-std=c++17"]
    args.fix = fix
    return args


def _tidy_notes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fix: bool):
    """Lint a copy of ``_SHIFTING_SRC`` and return clang-tidy's reported lines."""
    work = tmp_path / ("fix" if fix else "nofix")
    work.mkdir()
    src = work / "shifting.cpp"
    src.write_text(_SHIFTING_SRC, encoding="utf-8")
    monkeypatch.chdir(str(work))

    line_count = len(_SHIFTING_SRC.splitlines())
    # Model a PR that added the whole file: the diff's line numbers describe the
    # file *before* any formatting is applied.
    file_obj = FileObj(
        "shifting.cpp",
        additions=list(range(1, line_count + 1)),
        diff_chunks=[[1, line_count + 1]],
    )
    capture_clang_tools_output([file_obj], args=_tidy_order_args(fix))
    advice = file_obj.tidy_advice
    notes = [] if advice is None else advice.notes
    return [note.line for note in notes], src.read_text(encoding="utf-8")


def test_fix_does_not_shift_tidy_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """``--fix`` must not move clang-tidy's line numbers off the diff.

    clang-format's ``-i`` rewrites the file, but clang-tidy's ``--line-filter``
    and the PR review comments built from its output are both keyed to the
    event's diff. Running clang-format first would shift every diagnostic that
    follows a reflowed line, silently dropping some and misplacing the rest.
    """
    monkeypatch.setenv("COVERAGE_FILE", str(Path.cwd() / ".coverage"))

    baseline_lines, unfixed = _tidy_notes(tmp_path, monkeypatch, fix=False)
    fixed_lines, formatted = _tidy_notes(tmp_path, monkeypatch, fix=True)

    # Sanity: the fixture really does need reformatting, and --fix applied it.
    assert formatted != unfixed
    assert len(formatted.splitlines()) != len(_SHIFTING_SRC.splitlines())
    # Sanity: the checks above actually fire, so the comparison is meaningful.
    assert baseline_lines

    # The point of the test: fixing changes the file, not the diagnostics.
    assert fixed_lines == baseline_lines


def test_fix_with_format_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """``--fix`` combined with a clang-format PR review must still patch.

    A fixed file has no outstanding advice, but the review pass walks every
    file's advice and asserts each one carries a ``patched`` blob. Handing it a
    bare ``FormatAdvice`` there took the review down with an AssertionError.
    """
    monkeypatch.setenv("COVERAGE_FILE", str(Path.cwd() / ".coverage"))

    demo_dir = Path(__file__).parent.parent / "demo"
    shutil.copytree(str(demo_dir), str(tmp_path / "demo"))
    monkeypatch.chdir(str(tmp_path))

    demo_file = "demo/demo.cpp"
    args = _fix_args("file")
    args.format_review = True

    files = [FileObj(demo_file)]
    capture_clang_tools_output(files, args=args)

    advice = files[0].format_advice
    assert advice is not None
    # The file was fixed, so nothing is left to report...
    assert tally_format_advice(files) == 0
    # ...but the review still needs something to diff against.
    assert advice.patched is not None

    # And that diff is empty, so the review carries no suggestion for the file.
    review = ReviewComments()
    review.tool_total["clang-format"] = 0
    advice.get_suggestions_from_patch(files[0], False, review)
    assert review.suggestions == []
    assert review.tool_total["clang-format"] == 0
    assert review.full_patch["clang-format"] == ""
