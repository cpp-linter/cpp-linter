"""Helpers that delegate listing changed files to ``git-bot-feedback``."""

import subprocess

import git_bot_feedback as gbf

from ..common_fs import FileObj, has_line_changes
from ..loggers import logger


def get_repo_root_prefix(repo_root: str) -> str:
    """Get the path of :std:option:`--repo-root` inside its git repository.

    Git (and the git server's REST API) names changed files relative to the top level
    of the git repository, but cpp-linter names files relative to the
    :std:option:`--repo-root`. This prefix converts between the two.

    :param repo_root: The path to the repository root.
    :returns: The path with a trailing ``/`` (for example ``member/``), or an empty
        string if ``repo_root`` is the top level of a git repository or is not in a
        git repository.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-prefix"],
            capture_output=True,
            check=False,
            cwd=repo_root,
        )
    except OSError:  # pragma: no cover
        return ""  # git is not installed
    if result.returncode:
        logger.debug(
            "Could not find the repo root in a git repository: %s",
            result.stderr.decode(encoding="utf-8", errors="replace").strip(),
        )
        return ""
    return result.stdout.decode(encoding="utf-8").strip()


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
    repo_root: str = ".",
) -> list[FileObj]:
    """Retrieve changed files delegating to git-bot-feedback.

    :param file_filter: A `git_bot_feedback.FileFilter` to filter files.
    :param lines_changed_only: A value that dictates what file changes to focus on.
    :param diff_base: The commit or ref to use as the base of the diff.
    :param ignore_index: Ignore staged files in index.
    :param git_client: The `git_bot_feedback.GitClient` to delegate to.
    :param repo_root: The path to the repository root.
    :returns: A list of `FileObj` describing the changed files. The file names are
        relative to ``repo_root``. Changed files outside ``repo_root`` are left out.
    """
    lines_mode = to_gbf_lines_changed_only(lines_changed_only)
    base_diff_str = str(diff_base) if diff_base is not None else None

    prefix = get_repo_root_prefix(repo_root)
    # The changed files are named relative to the top level of the git repository,
    # but the `file_filter` patterns are relative to the repo root. So, when the repo
    # root is a sub-folder, only filter by file extension here, and apply the
    # `file_filter` after the names are made relative to the repo root.
    # An empty pattern after `!` explicitly does not ignore any path.
    git_filter = (
        gbf.FileFilter(ignore=["!"], extensions=list(file_filter.extensions))
        if prefix
        else file_filter
    )
    changed_map = await git_client.get_list_of_changed_files(
        git_filter,
        lines_mode,
        base_diff=base_diff_str,
        ignore_index=ignore_index,
    )
    file_objects: list[FileObj] = []
    for git_name in sorted(changed_map.keys()):
        file_name = git_name
        if prefix:
            if not git_name.startswith(prefix):
                continue  # the file is outside the repo root
            file_name = git_name[len(prefix) :]
            if not file_filter.is_qualified(file_name):
                continue
        file_diff = changed_map[git_name]
        diff_chunks = [list(h) for h in file_diff.diff_hunks]
        additions = file_diff.added_lines
        if has_line_changes(lines_changed_only, diff_chunks, additions):
            file_objects.append(FileObj(file_name, additions, diff_chunks))
    return file_objects
