import logging
import pytest
from cpp_linter.loggers import logger
from cpp_linter.common_fs.file_filter import FileFilter
from cpp_linter.git import parse_diff
from cpp_linter.git.git_str import parse_diff as parse_diff_str


TYPICAL_DIFF = "\n".join(
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


@pytest.mark.no_clang
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
    files = parse_diff(diff_str, FileFilter(extensions=["cpp"]), 0)
    assert caplog.messages, "this test is no longer needed; bug was fixed in pygit2"
    # if we get here test, then is satisfied
    assert not files  # no line changes means no file to focus on


@pytest.mark.no_clang
def test_typical_diff():
    """For coverage completeness. Also tests for files with spaces in the names."""
    file_filter = FileFilter(extensions=["cpp"])
    from_c = parse_diff(TYPICAL_DIFF, file_filter, 0)
    from_py = parse_diff_str(TYPICAL_DIFF, file_filter, 0)
    assert [f.serialize() for f in from_c] == [f.serialize() for f in from_py]
    for file_obj in from_c:
        # file name should have spaces
        assert " " in file_obj.name


@pytest.mark.no_clang
def test_binary_diff():
    """For coverage completeness"""
    diff_str = "\n".join(
        [
            "diff --git a/some picture.png b/some picture.png",
            "new file mode 100644",
            "Binary files /dev/null and b/some picture.png differ",
        ]
    )
    files = parse_diff_str(diff_str, FileFilter(extensions=["cpp"]), 0)
    # binary files are ignored during parsing
    assert not files


@pytest.mark.no_clang
def test_ignored_diff():
    """For coverage completeness"""
    files = parse_diff_str(TYPICAL_DIFF, FileFilter(extensions=["hpp"]), 0)
    # binary files are ignored during parsing
    assert not files


@pytest.mark.no_clang
def test_terse_hunk_header():
    """For coverage completeness"""
    diff_str = "\n".join(
        [
            "diff --git a/src/demo.cpp b/src/demo.cpp",
            "--- a/src/demo.cpp",
            "+++ b/src/demo.cpp",
            "@@ -3 +3 @@",
            "-#include <stdio.h>",
            "+#include <cstdio>",
            "@@ -4,0 +5,2 @@",
            "+auto main() -> int",
            "+{",
            "@@ -18 +17,2 @@ int main(){",
            "-    return 0;}",
            "+    return 0;",
            "+}",
        ]
    )
    file_filter = FileFilter(extensions=["cpp"])
    files = parse_diff_str(diff_str, file_filter, 0)
    assert files
    assert files[0].diff_chunks == [[3, 4], [5, 7], [17, 19]]
    git_files = parse_diff(diff_str, file_filter, 0)
    assert git_files
    assert files[0].diff_chunks == git_files[0].diff_chunks
