"""This module uses ``git`` CLI to get commit info. It also holds some functions
related to parsing diff output into a list of changed files."""

import logging
from pathlib import Path
from typing import Tuple, List, Optional, cast, Union

from pygit2 import (  # type: ignore
    Repository,
    Object as GitObject,
    Diff,
    DiffHunk,
    Commit,
    GIT_DELTA_ADDED,
    GIT_DELTA_MODIFIED,
    GIT_DELTA_RENAMED,
    GIT_STATUS_INDEX_NEW,
    GIT_STATUS_INDEX_MODIFIED,
    GIT_STATUS_INDEX_RENAMED,
    GitError,
)
from .. import CACHE_PATH
from ..common_fs import FileObj, has_line_changes
from ..common_fs.file_filter import FileFilter
from ..loggers import logger
from .git_str import parse_diff as legacy_parse_diff


def get_sha(repo: Repository, parent: Optional[int] = None) -> GitObject:
    """Uses ``git`` to fetch the full SHA hash of the current commit.

    .. note::
        This function is only used in local development environments, not in a
        Continuous Integration workflow.

    :param repo: The object representing the git repository.
    :param parent: This parameter's default value will fetch the SHA of the last commit.
        Set this parameter to the number of parent commits from the current tree's HEAD
        to get the desired commit's SHA hash instead.
    :returns: A `str` representing the commit's SHA hash.
    """
    return repo.revparse_single("HEAD" + (f"~{parent}" if parent is not None else ""))


STAGED_STATUS = (
    GIT_STATUS_INDEX_NEW,
    GIT_STATUS_INDEX_MODIFIED,
    GIT_STATUS_INDEX_RENAMED,
)


def get_diff(parents: int = 1) -> Diff:
    """Retrieve the diff info about a specified commit.

    :param parents: The number of parent commits related to the current commit.
    :returns: A `str` of the fetched diff.
    """
    repo = Repository(".")
    head = get_sha(repo)

    has_staged_files = False
    for _, status in repo.status().items():
        if status in STAGED_STATUS:
            has_staged_files = True
            break

    if has_staged_files:
        index = repo.index
        diff_obj = index.diff_to_tree(cast(Commit, head).tree)
        diff_name = f"HEAD...{head.short_id}"
    else:
        base = get_sha(repo, parents)  # only concerned with latest commit's diff
        diff_obj = repo.diff(base, head)
        diff_name = f"{head.short_id}...{base.short_id}"

    logger.info("getting diff between %s", diff_name)
    if logger.getEffectiveLevel() <= logging.DEBUG:  # pragma: no cover
        Path(CACHE_PATH, f"{diff_name}.diff").write_text(
            diff_obj.patch or "", encoding="utf-8"
        )
    return diff_obj


ADDITIVE_STATUS = (GIT_DELTA_RENAMED, GIT_DELTA_MODIFIED, GIT_DELTA_ADDED)


def parse_diff(
    diff_obj: Union[Diff, str],
    file_filter: FileFilter,
    lines_changed_only: int,
) -> List[FileObj]:
    """Parse a given diff into file objects.

    :param diff_obj: The complete git diff object for an event.
    :param file_filter: A `FileFilter` object.
    :param lines_changed_only: A value that dictates what file changes to focus on.
    :returns: A `list` of `FileObj` describing information about the files changed.

        .. note:: Deleted files are omitted because we only want to analyze updates.
    """
    file_objects: List[FileObj] = []
    if isinstance(diff_obj, str):
        try:
            diff_obj = Diff.parse_diff(diff_obj)
        except GitError as exc:
            logger.warning(f"pygit2.Diff.parse_diff() threw {exc}")
            return legacy_parse_diff(diff_obj, file_filter, lines_changed_only)
    for patch in diff_obj:
        if patch.delta.status not in ADDITIVE_STATUS:
            continue
        if not file_filter.is_source_or_ignored(patch.delta.new_file.path):
            continue
        diff_chunks, additions = parse_patch(patch.hunks)
        if has_line_changes(lines_changed_only, diff_chunks, additions):
            file_objects.append(
                FileObj(patch.delta.new_file.path, additions, diff_chunks)
            )
    return file_objects


def parse_patch(patch: List[DiffHunk]) -> Tuple[List[List[int]], List[int]]:
    """Parse a diff's patch accordingly.

    :param patch: The patch of hunks for 1 file.
    :returns:
        A `tuple` of lists where

        - Index 0 is the ranges of lines in the diff. Each item in this `list` is a
          2 element `list` describing the starting and ending line numbers.
        - Index 1 is a `list` of the line numbers that contain additions.
    """
    ranges: List[List[int]] = []
    # additions is a list line numbers in the diff containing additions
    additions: List[int] = []

    for hunk in patch:
        start_line, hunk_length = (hunk.new_start, hunk.new_lines)
        ranges.append([start_line, hunk_length + start_line])
        for line in hunk.lines:
            if line.origin == "+":
                additions.append(line.new_lineno)
    return (ranges, additions)
