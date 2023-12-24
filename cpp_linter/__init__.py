"""The Base module of the :mod:`cpp_linter` package. This holds the objects shared by
multiple modules."""
import os
from pathlib import Path
import logging
import platform
from typing import TYPE_CHECKING, List, Dict, Tuple, Any, Union, Optional
import shutil
from requests import Response

if TYPE_CHECKING:  # Used to avoid circular imports
    from cpp_linter.clang_format_xml import XMLFixit  # noqa: F401
    from cpp_linter.clang_tidy_yml import YMLFixit  # noqa: F401
    from cpp_linter.clang_tidy import TidyNotification  # noqa: F401

FOUND_RICH_LIB = False
try:
    from rich.logging import RichHandler

    FOUND_RICH_LIB = True

    logging.basicConfig(
        format="%(name)s: %(message)s",
        handlers=[RichHandler(show_time=False)],
    )

except ImportError:  # pragma: no cover
    logging.basicConfig()

#: The :py:class:`logging.Logger` object used for outputting data.
logger = logging.getLogger("CPP Linter")
if not FOUND_RICH_LIB:
    logger.debug("rich module not found")

# global constant variables
IS_ON_RUNNER = bool(os.getenv("CI"))
GITHUB_SHA = os.getenv("GITHUB_SHA", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", os.getenv("GIT_REST_API", ""))
IS_ON_WINDOWS = platform.system().lower() == "windows"
CACHE_PATH = Path(os.getenv("CPP_LINTER_CACHE", ".cpp-linter_cache"))
CLANG_FORMAT_XML = CACHE_PATH / "clang_format_output.xml"
CLANG_TIDY_YML = CACHE_PATH / "clang_tidy_output.yml"
CLANG_TIDY_STDOUT = CACHE_PATH / "clang_tidy_report.txt"
CHANGED_FILES_JSON = CACHE_PATH / "changed_files.json"


def make_headers(use_diff: bool = False) -> Dict[str, str]:
    """Create a `dict` for use in REST API headers.

    :param use_diff: A flag to indicate that the returned format should be in diff
        syntax.
    :returns: A `dict` to be used as headers in `requests` API calls.
    """
    headers = {
        "Accept": "application/vnd.github." + ("diff" if use_diff else "text+json"),
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    return headers


class FileObj:
    """A class to represent a single file being analyzed.

    :param name: The file name. This should use Unix style path delimiters (``/``),
        even on Windows.
    :param additions: A `list` of line numbers that have added changes in the diff.
        This value is used to populate the `lines_added` property.
    :param diff_chunks: The ranges that define the beginning and ending line numbers
        for all hunks in the diff.
    """

    def __init__(self, name: str, additions: List[int], diff_chunks: List[List[int]]):
        self.name: str = name  #: The file name
        self.additions: List[int] = additions
        """A list of line numbers that contain added changes. This will be empty if
        not focusing on lines changed only."""
        self.diff_chunks: List[List[int]] = diff_chunks
        """A list of line numbers that define the beginning and ending of hunks in the
        diff. This will be empty if not focusing on lines changed only."""
        self.lines_added: List[List[int]] = FileObj._consolidate_list_to_ranges(
            additions
        )
        """A list of line numbers that define the beginning and ending of ranges that
        have added changes. This will be empty if not focusing on lines changed only.
        """

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


class Globals:
    """Global variables for re-use (non-constant)."""

    TIDY_COMMENT: str = ""
    """The accumulated output of clang-tidy (gets appended to OUTPUT)"""
    FORMAT_COMMENT: str = ""
    OUTPUT: str = "<!-- cpp linter action -->\n# Cpp-Linter Report "
    """The accumulated body of the resulting comment that gets posted."""
    FILES: List[FileObj] = []
    """The responding payload containing info about changed files."""
    EVENT_PAYLOAD: Dict[str, Any] = {}
    """The parsed JSON of the event payload."""
    response_buffer: Response = Response()
    """A shared response object for `requests` module."""
    format_failed_count: int = 0
    """A total count of clang-format concerns"""
    tidy_failed_count: int = 0
    """A total count of clang-tidy concerns"""


class GlobalParser:
    """Global variables specific to output parsers. Each element in each of the
    following attributes represents a clang-tool's output for 1 source file.
    """

    tidy_notes = []  # type: List[TidyNotification]
    """This can only be a `list` of type
    :class:`~cpp_linter.clang_tidy.TidyNotification`."""
    tidy_advice = []  # type: List[YMLFixit]
    """This can only be a `list` of type :class:`~cpp_linter.clang_tidy_yml.YMLFixit`.
    """
    format_advice = []  # type: List[XMLFixit]
    """This can only be a `list` of type :class:`~cpp_linter.clang_format_xml.XMLFixit`.
    """


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


def log_response_msg() -> bool:
    """Output the response buffer's message on a failed request.

    :returns:
        A bool describing if response's status code was less than 400.
    """
    if Globals.response_buffer.status_code >= 400:
        logger.error(
            "response returned %d message: %s",
            Globals.response_buffer.status_code,
            Globals.response_buffer.text,
        )
        return False
    return True


def assemble_version_exec(tool_name: str, specified_version: str) -> Optional[str]:
    """Assembles the command to the executable of the given clang tool based on given
    version information.

    :param tool_name: The name of the clang tool to be executed.
    :param specified_version: The version number or the installed path to a version of
        the tool's executable.
    """
    semver = specified_version.split(".")
    exe_path = None
    if semver and semver[0].isdigit():  # version info is not a path
        # let's assume the exe is in the PATH env var
        exe_path = shutil.which(f"{tool_name}-{specified_version}")
    elif specified_version:  # treat value as a path to binary executable
        exe_path = shutil.which(tool_name, path=specified_version)
    if exe_path is not None:
        return exe_path
    return shutil.which(tool_name)
