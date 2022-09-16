"""This module uses ``git`` direct from CLI to get commit info."""
from pathlib import Path
import re
import subprocess
from typing import List, Dict, Any


def get_sha(parent: int = 0) -> str:
    """use ``git`` to fetch the full SHA of the current commit."""
    level = "HEAD" + ("" if not parent else f"^{parent}")
    result = subprocess.run(
        ["git", "rev-parse", level], capture_output=True, check=True
    )
    return result.stdout.decode(encoding="utf-8").rstrip("\n")


def get_diff(parents: int = 1) -> str:
    """Retrieve the diff info about a specified commit.

    :param commit_sha: The SHA for the commit to focus on.
    """
    result = subprocess.run(
        ["git", "diff", f"HEAD^{parents}"], capture_output=True, check=True
    )
    head = get_sha()
    base = get_sha(parents)
    Path(f"{head[-6:]}...{base[-6:]}.diff").write_bytes(result.stdout)
    return result.stdout.decode(encoding="utf-8")


def consolidate_list_to_ranges(just_numbers: List[int]) -> List[List[int]]:
    """A helper function to `filter_out_non_source_files()` that is only used when
    extracting the lines from a diff that contain additions."""
    result: List[List[int]] = []
    for i, n in enumerate(just_numbers):
        if not i:
            result.append([n])
        elif n - 1 != just_numbers[i - 1]:
            result[-1].append(just_numbers[i - 1] + 1)
            result.append([n])
        if i == len(just_numbers) - 1:
            result[-1].append(n + 1)
    return result


DIFF_FILE_DELIMITER = re.compile(r"diff --git a/.*?\sb/.*$", re.MULTILINE)
DIFF_FILE_NAME = re.compile(r"^\+\+\+\sb?/(.*)$", re.MULTILINE)
HUNK_INFO = re.compile(r"@@\s\-\d+,\d+\s\+(\d+,\d+)\s@@", re.MULTILINE)


def parse_diff(full_diff: str) -> List[Dict[str, Any]]:
    """Parse a given diff into file objects.

    :param full_diff: The complete diff for an event.
    :returns: A `list` of `dict` containing information about the files changed.
        .. note:: Deleted files are omitted because we only want to analyze updates.
    """
    file_objects = []
    file_diffs = DIFF_FILE_DELIMITER.split(full_diff)
    for diff in file_diffs:
        if not diff or diff.startswith("deleted file"):
            continue
        filename = DIFF_FILE_NAME.findall(diff)[0]
        status = "created" if diff.startswith("new file") else "changed"
        file_objects.append(dict(filename=filename, status=status))
        first_hunk = HUNK_INFO.search(diff)
        if first_hunk is None:
            continue
        patch = diff[first_hunk.start() :]
        # patch info not needed as we will be getting what we need from the diff here
        # file_objects[-1]["patch"] = patch
        ranges, additions = parse_patch(patch)
        file_objects[-1]["line_filter"] = dict(
            diff_chunks=ranges,
            lines_added=consolidate_list_to_ranges(additions),
        )
    return file_objects


def parse_patch(full_patch: str) -> tuple:
    """Parse a diff's patch accordingly.

    :param full_patch: The entire patch of hunks for 1 file.
    :returns: A `tuple` of lists where
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
