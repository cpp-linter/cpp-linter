"""This module uses ``git`` CLI to get commit info. It also holds some functions
related to parsing diff output into a list of changed files."""
from pathlib import Path
import re
import subprocess
from typing import Tuple, List, Dict, Any, Optional
from . import logger, CACHE_PATH


def get_sha(parent: int = 1) -> str:
    """Uses ``git`` to fetch the full SHA hash of the current commit.

    .. note::
        This function is only used in local development environments, not in a
        Continuous Integration workflow.

    :param parent: This parameter's default value will fetch the SHA of the last commit.
        Set this parameter to the number of parent commits from the current tree's HEAD
        to get the desired commit's SHA hash instead.
    :returns: A `str` representing the commit's SHA hash.
    """
    result = subprocess.run(
        ["git", "log", f"-{parent}", "--format=%H"], capture_output=True, check=True
    )
    return result.stdout.splitlines()[-1].decode(encoding="utf-8")


def get_diff(parents: int = 1) -> str:
    """Retrieve the diff info about a specified commit.

    :param parents: The number of parent commits related to the current commit.
    :returns: A `str` of the fetched diff.
    """
    head = "HEAD"
    base = get_sha(parents)
    logger.info("getting diff between %s...%s", head, base)
    result = subprocess.run(["git", "status", "-v"], capture_output=True, check=True)
    diff_start = result.stdout.find(b"diff --git")
    Path(CACHE_PATH, f"{head}...{base[:6]}.diff").write_bytes(
        result.stdout[diff_start:]
    )
    return result.stdout[diff_start:].decode(encoding="utf-8")


def consolidate_list_to_ranges(numbers: List[int]) -> List[List[int]]:
    """A helper function to `filter_out_non_source_files()` and `parse_diff()` that is
    only used when extracting the lines from a diff that contain additions.

    :param numbers: A `list` of integers representing the lines' numbers that contain
        additions.
    :returns: A consolidated sequence of lists. Each list will have 2 items
        describing the starting and ending lines of all line ``numbers``.
    """
    result: List[List[int]] = []
    for i, n in enumerate(numbers):
        if not i:
            result.append([n])
        elif n - 1 != numbers[i - 1]:
            result[-1].append(numbers[i - 1] + 1)
            result.append([n])
        if i == len(numbers) - 1:
            result[-1].append(n + 1)
    return result


DIFF_FILE_DELIMITER = re.compile(r"^diff --git a/.*$", re.MULTILINE)
DIFF_FILE_NAME = re.compile(r"^\+\+\+\sb?/(.*)$", re.MULTILINE)
DIFF_RENAMED_FILE = re.compile(r"^rename to (.*)$", re.MULTILINE)
DIFF_BINARY_FILE = re.compile(r"^Binary\sfiles\s", re.MULTILINE)
HUNK_INFO = re.compile(r"@@\s\-\d+,\d+\s\+(\d+,\d+)\s@@", re.MULTILINE)


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
        logger.warning(
            "Unrecognized diff starting with:\n%s",
            "\n".join(front_matter.splitlines()),
        )
    return None


def parse_diff(full_diff: str) -> List[Dict[str, Any]]:
    """Parse a given diff into file objects.

    :param full_diff: The complete diff for an event.
    :returns: A `list` of `dict` containing information about the files changed.

        .. note:: Deleted files are omitted because we only want to analyze updates.
    """
    file_objects: List[Dict[str, Any]] = []
    # logger.debug("full diff:\n%s", full_diff.strip("\n"))
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
        filename = filename_match.groups(0)[0]
        file_objects.append({"filename": filename})
        if first_hunk is None:
            continue
        ranges, additions = parse_patch(diff[first_hunk.start() :])
        file_objects[-1]["line_filter"] = {
            "diff_chunks": ranges,
            "lines_added": consolidate_list_to_ranges(additions),
        }
    return file_objects


def parse_patch(full_patch: str) -> Tuple[List[List[int]], List[int]]:
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
            start_line, hunk_length = [int(x) for x in chunk.split(",")]
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
