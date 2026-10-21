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
        ignore=_add_folder_globs(patterns),
        extensions=list(extensions or []),
        log_scope=tool_name,
    )


def _add_folder_globs(patterns: list[str]) -> list[str]:
    """Add a ``path/**`` glob for each plain ``path`` pattern.

    git-bot-feedback only matches a plain pattern to the files in a folder if the
    pattern is a folder in the working directory. The patterns are relative to the
    :std:option:`--repo-root`, which can be a sub-folder of the working directory.
    The glob matches the files in the folder wherever the folder is.
    """
    result: list[str] = []
    for pattern in patterns:
        result.append(pattern)
        path = pattern.replace("\\", "/").strip()
        negate = path.startswith("!")
        if negate:
            path = path[1:].lstrip()
        path = path.removeprefix("./").rstrip("/")
        if path in ("", ".") or path.startswith("..") or set(path) & set("*?[{"):
            continue  # not a plain path to a folder
        result.append(f"{'!' if negate else ''}{path}/**")
    return result


def list_source_files(file_filter: gbf.FileFilter, repo_root: str) -> list[FileObj]:
    """Make a list of source files in the ``repo_root`` directory that qualify
    according to the ``file_filter``.

    :returns: A list of `FileObj` objects without diff information. The file names
        are relative to ``repo_root``.
    """
    return [FileObj(name) for name in sorted(file_filter.walk_dir(repo_root))]
