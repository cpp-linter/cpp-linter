"""Tests for the ``--fix`` option that auto-applies clang-format fixes in place."""

import os
from pathlib import Path
import shutil

import pytest

from cpp_linter.common_fs import FileObj
from cpp_linter.clang_tools import capture_clang_tools_output
from cpp_linter.clang_tools.clang_format import tally_format_advice
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
