import os
import time
from os import environ
from pathlib import Path
from typing import TYPE_CHECKING, Any

import git_bot_feedback as gbf

from ..loggers import logger

if TYPE_CHECKING:  # pragma: no covers
    # circular import
    from ..clang_tools.clang_format import FormatAdvice
    from ..clang_tools.clang_tidy import TidyAdvice
    from ..clang_tools.patcher import DiffHunk

#: A path to generated cache artifacts. (only used when verbosity is in debug mode)
CACHE_PATH = Path(environ.get("CPP_LINTER_CACHE", ".cpp-linter_cache"))


def resolve_repo_root(repo_root: str) -> str:
    """Resolve the :std:option:`--repo-root` path.

    The path must be the current working directory or a directory inside it.
    Symbolic links are resolved before checking, so a link cannot lead outside the
    working directory either.

    :param repo_root: The value given to :std:option:`--repo-root`.
    :returns: The absolute path to the repository root.
    :raises ValueError: If the path is outside the working directory or is not a
        directory.
    """
    cwd = os.path.realpath(os.getcwd())
    root = os.path.realpath(repo_root)
    # The trailing separator keeps `/repo-other` from passing as inside `/repo`.
    if root != cwd and not root.startswith(os.path.join(cwd, "")):
        raise ValueError(
            f"--repo-root '{repo_root}' is outside the working directory '{cwd}'"
        )
    if not os.path.isdir(root):
        raise ValueError(f"--repo-root '{repo_root}' is not a directory")
    return root


def get_repo_root_prefix(repo_root: str, workspace_root: Path | None = None) -> str:
    """Get the path of :std:option:`--repo-root` inside its git repository.

    Git (and the git server's REST API) names changed files relative to the top level
    of the git repository, but cpp-linter names files relative to the
    :std:option:`--repo-root`. This prefix converts between the two.

    The top level of the git repository is the first of these that contains
    ``repo_root``:

    1. The closest folder, starting with ``repo_root`` itself, that has a ``.git``
       folder (or a ``.git`` file, as in a submodule). See
       `git_bot_feedback.nearest_git_root()`.
    2. The ``workspace_root``, as in a checkout made without git on a CI runner.
    3. The working directory.

    :param repo_root: The path to the repository root, as returned by
        `resolve_repo_root()`.
    :param workspace_root: The CI workspace's root folder, if any (see
        `~cpp_linter.rest_api.LinterClient.workspace_root()`).
    :returns: The path with a trailing ``/`` (for example ``member/``), or an empty
        string if ``repo_root`` is the top level.
    """
    root = Path(repo_root).resolve()
    candidates = (
        gbf.nearest_git_root(root),
        workspace_root.resolve() if workspace_root is not None else None,
        Path.cwd().resolve(),
    )
    top = next(
        (path for path in candidates if path and root.is_relative_to(path)), root
    )
    prefix = root.relative_to(top).as_posix()
    return "" if prefix == "." else f"{prefix}/"


class FileObj:
    """A class to represent a single file being analyzed.

    :param name: The file name. This should use Unix style path delimiters (``/``),
        even on Windows.
    :param additions: A `list` of line numbers that have added changes in the diff.
        This value is used to populate the `lines_added` property.
    :param diff_chunks: The ranges that define the beginning and ending line numbers
        for all hunks in the diff.
    """

    def __init__(
        self,
        name: str,
        additions: list[int] | None = None,
        diff_chunks: list[list[int]] | None = None,
    ):
        self.name: str = name  #: The file name
        self.additions: list[int] = additions or []
        """A list of line numbers that contain added changes. This will be empty if
        not focusing on lines changed only."""
        self.diff_chunks: list[list[int]] = diff_chunks or []
        """A list of line numbers that define the beginning and ending of hunks in the
        diff. This will be empty if not focusing on lines changed only."""
        self.lines_added: list[list[int]] = FileObj._consolidate_list_to_ranges(
            additions or []
        )
        """A list of line numbers that define the beginning and ending of ranges that
        have added changes. This will be empty if not focusing on lines changed only.
        """
        #: The results from clang-tidy
        self.tidy_advice: TidyAdvice | None = None
        #: The results from clang-format
        self.format_advice: FormatAdvice | None = None

    def __repr__(self) -> str:
        return f"<FileObj {self.name} added:{self.additions} chunks:{self.diff_chunks}>"

    @staticmethod
    def _consolidate_list_to_ranges(numbers: list[int]) -> list[list[int]]:
        """A helper function that is only used after parsing the lines from a diff that
        contain additions.

        :param numbers: A `list` of integers representing the lines' numbers that
            contain additions.
        :returns: A consolidated sequence of lists. Each list will have 2 items
            describing the starting and ending lines of all line ``numbers``.
        """
        result: list[list[int]] = []
        for i, n in enumerate(numbers):
            if not i:
                result.append([n])
            elif n - 1 != numbers[i - 1]:
                result[-1].append(numbers[i - 1])
                result.append([n])
            if i == len(numbers) - 1:
                result[-1].append(n)
        return result

    def range_of_changed_lines(
        self, lines_changed_only: int, get_ranges: bool = False
    ) -> list[int] | list[list[int]]:
        """Assemble a list of lines changed.

        :param lines_changed_only: A flag to indicate the focus of certain lines.

            - ``0``: focuses on all lines in a file(s).
            - ``1``: focuses on any lines shown in the event's diff (may include
              unchanged lines).
            - ``2``: focuses strictly on lines in the diff that contain additions.
        :param get_ranges: A flag to return a list of sequences representing
            :py:class:`range` parameters. Defaults to `False` since this is only
            required when constructing clang-tidy or clang-format CLI arguments.
        :returns:
            A list of line numbers for which to give attention. If ``get_ranges`` is
            asserted, then the returned list will be a list of ranges. If
            ``lines_changed_only`` is ``0``, then an empty list is returned.
        """
        if lines_changed_only:
            ranges = self.diff_chunks if lines_changed_only == 1 else self.lines_added
            if get_ranges:
                return ranges
            return self.additions
        # we return an empty list (instead of None) here so we can still iterate it
        return []  # type: ignore[return-value]

    def serialize(self) -> dict[str, Any]:
        """For easy debugging, use this method to serialize the `FileObj` into a json
        compatible `dict`."""
        return {
            "filename": self.name,
            "line_filter": {
                "diff_chunks": self.diff_chunks,
                "lines_added": self.lines_added,
            },
        }

    def is_hunk_contained(self, hunk: "DiffHunk") -> tuple[int, int] | None:
        """Does a given ``hunk`` start and end within a single diff hunk?

        This also includes some compensations for hunk headers that are oddly formed.

        .. tip:: This is mostly useful to create comments that can be posted within a
            git changes' diff. Ideally, designed for PR reviews based on patches
            generated by clang tools' output.

        :returns: The appropriate starting and ending line numbers of the given hunk.
            If hunk cannot fit in a single hunk, this returns `None`.
        """
        if hunk.old_lines > 0:
            start = hunk.old_start
            # span of old_lines is an inclusive range
            end = hunk.old_start + hunk.old_lines - 1
        else:  # if number of old lines is 0
            # start hunk at new line number
            start = hunk.new_start
            # make it span 1 line
            end = start
        return self.is_range_contained(start, end)

    def is_range_contained(self, start: int, end: int) -> tuple[int, int] | None:
        """Does the given ``start`` and ``end`` line numbers fit within a single diff
        hunk?

        This is a helper function to `is_hunk_contained()`.

        .. tip:: This is mostly useful to create comments that can be posted within a
            git changes' diff. Ideally, designed for PR reviews based on patches
            generated by clang tools' output.

        :returns: The appropriate starting and ending line numbers of the given hunk.
            If hunk cannot fit in a single hunk, this returns `None`.
        """
        for hunk in self.diff_chunks:
            chunk_range = range(hunk[0], hunk[1])
            if start in chunk_range and end in chunk_range:
                return (start, end)
        logger.warning(
            "lines %d - %d are not within a single diff hunk for file %s.",
            start,
            end,
            self.name,
        )
        return None

    def read_with_timeout(
        self, repo_root: str, timeout_ns: int = 1_000_000_000
    ) -> bytes:
        """Read the entire file's contents.

        :param repo_root: The path that the file's `name` is relative to.
        :param timeout_ns: The number of nanoseconds to wait till timeout occurs.
            Defaults to 1 second.

        :returns: The bytes read from the file.

        :raises FileIOTimeout: When the operation did not succeed due to a timeout.
        :raises OSError: When the file could not be opened due to an `OSError`.
        """
        contents = b""
        success = False
        exception: OSError | FileIOTimeout = FileIOTimeout(
            f"Failed to read from file '{self.name}' within "
            + f"{round(timeout_ns / 1_000_000_000, 2)} seconds"
        )
        timeout = time.monotonic_ns() + timeout_ns
        while not success and time.monotonic_ns() < timeout:
            try:
                with open(Path(repo_root, self.name), "rb") as f:
                    while not success and time.monotonic_ns() < timeout:
                        if f.readable():
                            contents = f.read()
                            success = True
                        else:  # pragma: no cover
                            time.sleep(0.001)  # Sleep to prevent busy-waiting
            except OSError as exc:  # pragma: no cover
                exception = exc
        if not success and exception:  # pragma: no cover
            raise exception
        return contents

    def read_write_with_timeout(
        self,
        repo_root: str,
        data: bytes | bytearray,
        timeout_ns: int = 1_000_000_000,
    ) -> bytes:
        """Read then write the entire file's contents.

        :param repo_root: The path that the file's `name` is relative to.
        :param data: The bytes to write to the file. This will overwrite the contents
            being read beforehand.
        :param timeout_ns: The number of nanoseconds to wait till timeout occurs.
            Defaults to 1 second.

        :returns: The bytes read from the file.

        :raises FileIOTimeout: When the operation did not succeed due to a timeout.
        :raises OSError: When the file could not be opened due to an `OSError`.
        """
        success = False
        exception: OSError | FileIOTimeout = FileIOTimeout(
            f"Failed to read then write file '{self.name}' within "
            + f"{round(timeout_ns / 1_000_000_000, 2)} seconds"
        )
        original_data = b""
        timeout = time.monotonic_ns() + timeout_ns
        while not success and time.monotonic_ns() < timeout:
            try:
                with open(Path(repo_root, self.name), "r+b") as f:
                    while not success and time.monotonic_ns() < timeout:
                        if f.readable():
                            original_data = f.read()
                            f.seek(0)
                        else:  # pragma: no cover
                            time.sleep(0.001)  # Sleep to prevent busy-waiting
                            continue
                        while not success and time.monotonic_ns() < timeout:
                            if f.writable():
                                f.write(data)
                                f.truncate()
                                success = True
                            else:  # pragma: no cover
                                time.sleep(0.001)  # Sleep to prevent busy-waiting
            except OSError as exc:  # pragma: no cover
                exception = exc
        if not success and exception:  # pragma: no cover
            raise exception
        return original_data


class FileIOTimeout(Exception):
    """An exception thrown when a file operation timed out."""


def has_line_changes(
    lines_changed_only: int, diff_chunks: list[list[int]], additions: list[int]
) -> bool:
    """Does this file actually apply to condition specified by ``lines_changed_only``?

    :param lines_changed_only: A value that means:

        - 0 = We don't care. Analyze the whole file.
        - 1 = Only analyze lines in the diff chunks, which may include unchanged
          lines but not lines with subtractions.
        - 2 = Only analyze lines with additions.
    :param diff_chunks: The ranges of lines in the diff for a single file.
    :param additions: The lines with additions in the diff for a single file.
    """
    return (
        (lines_changed_only == 1 and len(diff_chunks) > 0)
        or (lines_changed_only == 2 and len(additions) > 0)
        or not lines_changed_only
    )


def get_line_cnt_from_cols(data: bytes, offset: int) -> tuple[int, int]:
    """Gets a line count and columns offset from a file's absolute offset.

    :param data: Bytes content to analyze.
    :param offset: The byte offset to translate

    :returns:
        A `tuple` of 2 `int` numbers:

        - Index 0 is the line number for the given offset.
        - Index 1 is the column number for the given offset on the line.
    """
    # logger.debug("Getting line count from %s at offset %d", file_path, offset)
    contents = data[:offset]
    return (contents.count(b"\n") + 1, offset - contents.rfind(b"\n"))
