"""This was reintroduced to deal with any bugs in pygit2 (or the libgit2 C library it
binds to). The `parse_diff()` function here is only used when
:py:meth:`pygit2.Diff.parse_diff()` function fails in `cpp_linter.git.parse_diff()`"""

import re
from typing import Optional, List, Tuple, cast
from ..common_fs import FileObj, has_line_changes
from ..common_fs.file_filter import FileFilter
from ..loggers import logger


DIFF_FILE_DELIMITER = re.compile(r"^diff --git a/.*$", re.MULTILINE)
DIFF_FILE_NAME = re.compile(r"^\+\+\+\sb?/(.*)$", re.MULTILINE)
DIFF_RENAMED_FILE = re.compile(r"^rename to (.*)$", re.MULTILINE)
DIFF_BINARY_FILE = re.compile(r"^Binary\sfiles\s", re.MULTILINE)
HUNK_INFO = re.compile(r"^@@\s\-\d+,?\d*\s\+(\d+,?\d*)\s@@", re.MULTILINE)


def _get_filename_from_diff(front_matter: str) -> Optional[re.Match]:
    """Get the filename from content in the given diff front matter."""
    filename_match = DIFF_FILE_NAME.search(front_matter)
    if filename_match is not None:
        return filename_match

    # check for renamed file name
    rename_match = DIFF_RENAMED_FILE.search(front_matter)
    if rename_match is not None and front_matter.lstrip().startswith("similarity"):
        return rename_match
    # We may need to compensate for other instances where the filename is
    # not directly after `+++ b/`. Binary files are another example of this.
    if DIFF_BINARY_FILE.search(front_matter) is None:
        # log the case and hope it helps in the future
        logger.warning(  # pragma: no cover
            "Unrecognized diff starting with:\n%s",
            "\n".join(front_matter.splitlines()),
        )
    return None


def parse_diff(
    full_diff: str,
    file_filter: FileFilter,
    lines_changed_only: int,
) -> List[FileObj]:
    """Parse a given diff into file objects.

    :param full_diff: The complete diff for an event.
    :param file_filter: A `FileFilter` object.
    :param lines_changed_only: A value that dictates what file changes to focus on.
    :returns: A `list` of `FileObj` instances containing information about the files
        changed.
    """
    file_objects: List[FileObj] = []
    logger.error("Using pure python to parse diff because pygit2 failed!")
    file_diffs = DIFF_FILE_DELIMITER.split(full_diff.lstrip("\n"))
    for diff in file_diffs:
        if not diff or diff.lstrip().startswith("deleted file"):
            continue
        first_hunk = HUNK_INFO.search(diff)
        hunk_start = -1 if first_hunk is None else first_hunk.start()
        diff_front_matter = diff[:hunk_start]
        filename_match = _get_filename_from_diff(diff_front_matter)
        if filename_match is None:
            continue
        filename = cast(str, filename_match.groups(0)[0])
        if first_hunk is None:
            continue
        if not file_filter.is_source_or_ignored(filename):
            continue
        diff_chunks, additions = _parse_patch(diff[first_hunk.start() :])
        if has_line_changes(lines_changed_only, diff_chunks, additions):
            file_objects.append(FileObj(filename, additions, diff_chunks))
    return file_objects


def _parse_patch(full_patch: str) -> Tuple[List[List[int]], List[int]]:
    """Parse a diff's patch accordingly.

    :param full_patch: The entire patch of hunks for 1 file.
    :returns:
        A `tuple` of lists where

        - Index 0 is the ranges of lines in the diff. Each item in this `list` is a
          2 element `list` describing the starting and ending line numbers.
        - Index 1 is a `list` of the line numbers that contain additions.
    """
    ranges: List[List[int]] = []
    # additions is a list line numbers in the diff containing additions
    additions: List[int] = []
    line_numb_in_diff: int = 0
    chunks = HUNK_INFO.split(full_patch)
    for index, chunk in enumerate(chunks):
        if index % 2 == 1:
            # each odd element holds the starting line number and number of lines
            if "," in chunk:
                start_line, hunk_length = [int(x) for x in chunk.split(",")]
            else:
                start_line = int(chunk)
                hunk_length = 1
            ranges.append([start_line, hunk_length + start_line])
            line_numb_in_diff = start_line
            continue
        # each even element holds the actual line changes
        for i, line in enumerate(chunk.splitlines()):
            if line.startswith("+"):
                additions.append(line_numb_in_diff)
            if not line.startswith("-") and i:  # don't increment on first line
                line_numb_in_diff += 1
    return (ranges, additions)
