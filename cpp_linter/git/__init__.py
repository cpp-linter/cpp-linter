"""Helpers that delegate listing changed files to ``git-bot-feedback``."""

import git_bot_feedback as gbf

from ..common_fs import FileObj, has_line_changes


def to_gbf_lines_changed_only(
    lines_changed_only: int | gbf.LinesChangedOnly,
) -> gbf.LinesChangedOnly:
    """Convert an integer lines_changed_only value to git_bot_feedback.LinesChangedOnly."""
    if isinstance(lines_changed_only, gbf.LinesChangedOnly):
        return lines_changed_only
    if lines_changed_only == 1:
        return gbf.LinesChangedOnly.Diff
    if lines_changed_only == 2:
        return gbf.LinesChangedOnly.On
    return gbf.LinesChangedOnly.Off


async def get_list_of_changed_files(
    git_client: gbf.GitClient,
    file_filter: gbf.FileFilter,
    lines_changed_only: int,
    diff_base: None | int | str = None,
    ignore_index: bool = False,
) -> list[FileObj]:
    """Retrieve changed files delegating to git-bot-feedback.

    :param file_filter: A `git_bot_feedback.FileFilter` to filter files.
    :param lines_changed_only: A value that dictates what file changes to focus on.
    :param diff_base: The commit or ref to use as the base of the diff.
    :param ignore_index: Ignore staged files in index.
    :param git_client: The `git_bot_feedback.GitClient` to delegate to.
    :returns: A list of `FileObj` describing the changed files.
    """
    lines_mode = to_gbf_lines_changed_only(lines_changed_only)
    base_diff_str = str(diff_base) if diff_base is not None else None

    changed_map = await git_client.get_list_of_changed_files(
        file_filter,
        lines_mode,
        base_diff=base_diff_str,
        ignore_index=ignore_index,
    )
    file_objects: list[FileObj] = []
    for file_name in sorted(changed_map.keys()):
        file_diff = changed_map[file_name]
        diff_chunks = [list(h) for h in file_diff.diff_hunks]
        additions = file_diff.added_lines
        if has_line_changes(lines_changed_only, diff_chunks, additions):
            file_objects.append(FileObj(file_name, additions, diff_chunks))
    return file_objects
