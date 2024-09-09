from os import environ
from pathlib import Path
from typing import List, Dict, Any, Union, Tuple, Optional, TYPE_CHECKING
from pygit2 import DiffHunk  # type: ignore
from ..loggers import logger

if TYPE_CHECKING:  # pragma: no covers
    # circular import
    from ..clang_tools.clang_tidy import TidyAdvice
    from ..clang_tools.clang_format import FormatAdvice

#: A path to generated cache artifacts. (only used when verbosity is in debug mode)
CACHE_PATH = Path(environ.get("CPP_LINTER_CACHE", ".cpp-linter_cache"))


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
        additions: Optional[List[int]] = None,
        diff_chunks: Optional[List[List[int]]] = None,
    ):
        self.name: str = name  #: The file name
        self.additions: List[int] = additions or []
        """A list of line numbers that contain added changes. This will be empty if
        not focusing on lines changed only."""
        self.diff_chunks: List[List[int]] = diff_chunks or []
        """A list of line numbers that define the beginning and ending of hunks in the
        diff. This will be empty if not focusing on lines changed only."""
        self.lines_added: List[List[int]] = FileObj._consolidate_list_to_ranges(
            additions or []
        )
        """A list of line numbers that define the beginning and ending of ranges that
        have added changes. This will be empty if not focusing on lines changed only.
        """
        #: The results from clang-tidy
        self.tidy_advice: Optional["TidyAdvice"] = None
        #: The results from clang-format
        self.format_advice: Optional["FormatAdvice"] = None

    def __repr__(self) -> str:
        return f"<FileObj {self.name} added:{self.additions} chunks:{self.diff_chunks}>"

    @staticmethod
    def _consolidate_list_to_ranges(numbers: List[int]) -> List[List[int]]:
        """A helper function that is only used after parsing the lines from a diff that
        contain additions.

        :param numbers: A `list` of integers representing the lines' numbers that
            contain additions.
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

    def range_of_changed_lines(
        self, lines_changed_only: int, get_ranges: bool = False
    ) -> Union[List[int], List[List[int]]]:
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

    def serialize(self) -> Dict[str, Any]:
        """For easy debugging, use this method to serialize the `FileObj` into a json
        compatible `dict`."""
        return {
            "filename": self.name,
            "line_filter": {
                "diff_chunks": self.diff_chunks,
                "lines_added": self.lines_added,
            },
        }

    def is_hunk_contained(self, hunk: DiffHunk) -> Optional[Tuple[int, int]]:
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

    def is_range_contained(self, start: int, end: int) -> Optional[Tuple[int, int]]:
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


def has_line_changes(
    lines_changed_only: int, diff_chunks: List[List[int]], additions: List[int]
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


def get_line_cnt_from_cols(file_path: str, offset: int) -> Tuple[int, int]:
    """Gets a line count and columns offset from a file's absolute offset.

    :param file_path: Path to file.
    :param offset: The byte offset to translate

    :returns:
        A `tuple` of 2 `int` numbers:

        - Index 0 is the line number for the given offset.
        - Index 1 is the column number for the given offset on the line.
    """
    # logger.debug("Getting line count from %s at offset %d", file_path, offset)
    contents = Path(file_path).read_bytes()[:offset]
    return (contents.count(b"\n") + 1, offset - contents.rfind(b"\n"))
