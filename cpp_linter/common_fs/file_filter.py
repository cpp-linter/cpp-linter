"""Helpers for building and using a `git_bot_feedback.FileFilter`."""

import git_bot_feedback as gbf

from . import FileObj


def make_file_filter(
    ignore_value: str = "",
    extensions: list[str] | None = None,
    not_ignored: list[str] | None = None,
    tool_name: str | None = None,
) -> gbf.FileFilter:
    """Create a file filter from the user's input.

    :param ignore_value: The user input specified via :std:option:`--ignore`
        (patterns separated by ``|``, where a leading ``!`` means "not ignored").
    :param extensions: A list of file extensions in which to focus.
    :param not_ignored: A list of files or paths that will be explicitly not ignored.
    :param tool_name: A clang tool name for which the file filter is specifically
        applied. This only gets used in debug statements.
    """
    patterns = ignore_value.split("|") if ignore_value else []
    patterns.extend(f"!{path}" for path in not_ignored or [])
    return gbf.FileFilter(
        ignore=patterns, extensions=list(extensions or []), log_scope=tool_name
    )


def list_source_files(file_filter: gbf.FileFilter) -> list[FileObj]:
    """Make a list of source files in the current working directory that qualify
    according to the ``file_filter``.

    :returns: A list of `FileObj` objects without diff information.
    """
    return [FileObj(name) for name in sorted(file_filter.walk_dir("."))]
