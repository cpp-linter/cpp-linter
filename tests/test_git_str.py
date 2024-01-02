import logging
import pytest
from cpp_linter.loggers import logger
from cpp_linter.git import parse_diff
from cpp_linter.git.git_str import parse_diff as parse_diff_str


def test_pygit2_bug1260(caplog: pytest.LogCaptureFixture):
    """This test the legacy approach of parsing a diff str using pure python regex
    patterns.

    See https://github.com/libgit2/pygit2/issues/1260 for details
    """
    diff_str = "\n".join(
        [
            "diff --git a/path/for/Some file.cpp b/path/to/Some file.cpp",
            "similarity index 99%",
            "rename from path/for/Some file.cpp",
            "rename to path/to/Some file.cpp",
        ]
    )
    caplog.set_level(logging.WARNING, logger=logger.name)
    # the bug in libgit2 should trigger a call to
    # cpp_linter.git_str.legacy_parse_diff()
    files = parse_diff(diff_str, ["cpp"], [], [])
    assert caplog.messages, "this test is no longer needed; bug was fixed in pygit2"
    # if we get here test, then is satisfied
    assert not files  # no line changes means no file to focus on

def test_typical_diff():
    """For coverage completeness. Also tests for files with spaces in the names."""
    diff_str = "\n".join(
        [
            "diff --git a/path/for/Some file.cpp b/path/to/Some file.cpp",
            "--- a/path/for/Some file.cpp",
            "+++ b/path/to/Some file.cpp",
            "@@ -3,7 +3,7 @@",
            " ",
            " ",
            " ",
            "-#include <some_lib/render/animation.hpp>",
            "+#include <some_lib/render/animations.hpp>",
            " ",
            " ",
            " \n",
        ]
    )
    from_c = parse_diff(diff_str, ["cpp"], [], [])
    from_py = parse_diff_str(diff_str, ["cpp"], [], [])
    assert [f.serialize() for f in from_c] == [f.serialize() for f in from_py]
    for file_obj in from_c:
        # file name should have spaces
        assert " " in file_obj.name


def test_binary_diff():
    """For coverage completeness"""
    diff_str = "\n".join(
        [
            "diff --git a/some picture.png b/some picture.png",
            "new file mode 100644",
            "Binary files /dev/null and b/some picture.png differ",
        ]
    )
    files = parse_diff_str(diff_str, ["cpp"], [], [])
    # binary files are ignored during parsing
    assert not files
