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
    head = get_sha()
    base = get_sha(parents)
    result = subprocess.run(
        ["git", "diff", f"HEAD^{parents}"], capture_output=True, check=True
    )
    Path(f"{head[-6:]}...{base[-6:]}.diff").write_bytes(result.stdout)
    return result.stdout.decode(encoding="utf-8")

DIFF_FILE_DELIMITER = re.compile(r"diff --git a/.*?\sb/.*$", re.MULTILINE)


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

def parse_diff(full_patch: str) -> List[Dict[str, Any]]:
    """Parse a given diff into file objects"""
    file_objects = []
    file_diffs = DIFF_FILE_DELIMITER.split(full_patch)
    for diff in file_diffs:
        if not diff:
            continue
        filename = re.findall(r"^\+\+\+ b/(.*)$", diff, re.MULTILINE)[0]
        file_objects.append(dict(filename=filename))
        first_hunk = diff.find("@@ -")
        if first_hunk == -1:
            file_objects[-1]["patch"] = ""
            continue
        patch = diff[first_hunk:]
        file_objects[-1]["patch"] = patch
        ranges: List[List[int]] = []
        # additions is a list line numbers in the diff containing additions
        additions: List[int] = []
        line_numb_in_diff: int = 0
        for line in patch.splitlines(keepends=True):
            if line.startswith("+"):
                additions.append(line_numb_in_diff)
            if line.startswith("@@ -"):
                hunk = line[line.find(" +") + 2 : line.find(" @@")].split(",")
                start_line, hunk_length = [int(x) for x in hunk]
                ranges.append([start_line, hunk_length + start_line])
                line_numb_in_diff = start_line
            elif not line.startswith("-"):
                line_numb_in_diff += 1
        file_objects[-1]["line_filter"] = dict(
            diff_chunks=ranges,
            lines_added=consolidate_list_to_ranges(additions),
        )
    return file_objects
