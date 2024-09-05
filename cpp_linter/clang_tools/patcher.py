"""A module to contain the abstractions about creating suggestions from a diff generated
by the clang tool's output."""

from abc import ABC
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from pygit2 import Patch  # type: ignore
from ..common_fs import FileObj

try:
    from pygit2.enums import DiffOption  # type: ignore

    INDENT_HEURISTIC = DiffOption.INDENT_HEURISTIC
except ImportError:  # if pygit2.__version__ < 1.14
    from pygit2 import GIT_DIFF_INDENT_HEURISTIC  # type: ignore

    INDENT_HEURISTIC = GIT_DIFF_INDENT_HEURISTIC


class Suggestion:
    """A data structure to contain information about a single suggestion.

    :param file_name: The path to the file that this suggestion pertains.
        This should use posix path separators.
    """

    def __init__(self, file_name: str) -> None:
        #: The file's line number starting the suggested change.
        self.line_start: int = -1
        #: The file's line number ending the suggested change.
        self.line_end: int = -1
        #: The file's path about the suggested change.
        self.file_name: str = file_name
        #: The markdown comment about the suggestion.
        self.comment: str = ""

    def serialize_to_github_payload(self) -> Dict[str, Any]:
        """Serialize this object into a JSON compatible with Github's REST API."""
        assert self.line_end > 0, "ending line number unknown"
        result = {"path": self.file_name, "body": self.comment, "line": self.line_end}
        if self.line_start != self.line_end and self.line_start > 0:
            result["start_line"] = self.line_start
        return result


class ReviewComments:
    """A data structure to contain PR review comments from a specific clang tool."""

    def __init__(self) -> None:
        #: The list of actual comments
        self.suggestions: List[Suggestion] = []

        self.total: int = 0
        """The total number of concerns.

        This may not equate to the length of `suggestions` because there is no
        guarantee that all suggestions will fit within the PR's diff."""

        self.full_patch: str = ""
        """The full patch of all the suggestions (including those that will not
        fit within the diff)"""

    def serialize_to_github_payload(
        self, tool_name: str
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Serialize this object into a summary and list of comments compatible
        with Github's REST API.

        :param tool_name: The clang tool's name that generated the suggestions.

        :returns: The returned tuple contains a brief summary (at index ``0``)
            that contains markdown text describing the summary of the review
            comments.

            The list of `suggestions` (at index ``1``) is the serialized JSON
            object.
        """
        len_suggestions = len(self.suggestions)
        summary = ""
        comments = []
        if len_suggestions:
            comments = [x.serialize_to_github_payload() for x in self.suggestions]
            if self.total and self.total != len_suggestions:
                summary += f"Only {len_suggestions} out of {self.total} {tool_name} "
                summary += "concerns fit within this pull request's diff.\n"
        if self.full_patch:
            summary += f"\n<details><summary>Click here for the full {tool_name} patch"
            summary += (
                f"</summary>\n\n\n```diff\n{self.full_patch}\n```\n\n\n</details>\n\n"
            )
        elif not self.total:
            summary += f"No concerns from {tool_name}.\n"
        result = (summary, comments)
        return result


class PatchMixin(ABC):
    """An abstract mixin that unified parsing of the suggestions into
    PR review comments."""

    def __init__(self) -> None:
        #: A unified diff of the applied fixes from the clang tool's output
        self.patched: Optional[bytes] = None

    def get_suggestion_help(self, start, end) -> str:
        """Create helpful text about what the suggestion aims to fix.

        The parameters ``start`` and ``end`` are the line numbers (relative to file's
        original content) encapsulating the suggestion.
        """

        raise NotImplementedError("derivative must implement this abstract method")

    def get_suggestions_from_patch(
        self, file_obj: FileObj, summary_only: bool, review_comments: ReviewComments
    ):
        """Create a list of suggestions from the tool's `patched` output.

        Results are stored in the ``review_comments`` parameter (passed by reference).
        """

        assert (
            self.patched
        ), f"{self.__class__.__name__} has no suggestions for {file_obj.name}"
        patch = Patch.create_from(
            Path(file_obj.name).read_bytes(),
            self.patched,
            file_obj.name,
            file_obj.name,
            context_lines=0,  # exclude any surrounding unchanged lines
            flag=INDENT_HEURISTIC,
        )
        review_comments.full_patch += f"{patch.text}"
        for hunk in patch.hunks:
            review_comments.total += 1
            if summary_only:
                continue
            new_hunk_range = file_obj.is_hunk_contained(hunk)
            if new_hunk_range is None:
                continue
            start_line, end_line = new_hunk_range
            comment = Suggestion(file_obj.name)
            body = self.get_suggestion_help(start=start_line, end=end_line)
            if start_line < end_line:
                comment.line_start = start_line
            comment.line_end = end_line
            removed = []
            suggestion = ""
            for line in hunk.lines:
                if line.origin in ("+", " "):
                    suggestion += f"{line.content}"
                else:
                    line_numb = line.new_lineno
                    removed.append(line_numb)
            if not suggestion and removed:
                body += "\nPlease remove the line(s)\n- "
                body += "\n- ".join([str(x) for x in removed])
            else:
                body += f"\n```suggestion\n{suggestion}```"
            comment.comment = body
            review_comments.suggestions.append(comment)
