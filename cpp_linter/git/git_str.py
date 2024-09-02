"""This was reintroduced to deal with any bugs in pygit2 (or the libgit2 C library it
binds to). The `parse_diff()` function here is only used when
:py:meth:`pygit2.Diff.parse_diff()` function fails in `cpp_linter.git.parse_diff()`"""

from typing import List
import unidiff
from ..common_fs import FileObj, has_line_changes
from ..common_fs.file_filter import FileFilter
from ..loggers import logger


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
    patch = unidiff.PatchSet(full_diff)
    for diff_file in patch:
        if diff_file.is_added_file or diff_file.is_modified_file or diff_file.is_rename:
            file_name = diff_file.target_file.lstrip("b/")
            if not file_filter.is_source_or_ignored(file_name):
                continue
            additions = []
            diff_chunks = []
            for diff_hunk in diff_file:
                if diff_hunk.added:
                    hunk_start = diff_hunk.target_start
                    diff_chunks.append(
                        [hunk_start, hunk_start + diff_hunk.target_length]
                    )
                    for line in diff_hunk:
                        if line.line_type == "+":
                            line_number = line.target_line_no
                            assert line_number is not None
                            additions.append(line_number)
            if additions and has_line_changes(
                lines_changed_only, diff_chunks, additions
            ):
                file_objects.append(FileObj(file_name, additions, diff_chunks))
    return file_objects
