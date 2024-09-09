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

        self.tool_total: Dict[str, int] = {"clang-tidy": 0, "clang-format": 0}
        """The total number of concerns about a specific clang tool.

        This may not equate to the length of `suggestions` because
        1. There is no guarantee that all suggestions will fit within the PR's diff.
        2. Suggestions are a combined result of advice from both tools.
        """

        self.full_patch: Dict[str, str] = {"clang-tidy": "", "clang-format": ""}
        """The full patch of all the suggestions (including those that will not
        fit within the diff)"""

    def merge_similar_suggestion(self, suggestion: Suggestion) -> bool:
        """Merge a given ``suggestion`` into a similar `Suggestion`

        :returns: `True` if the suggestion was merged, otherwise `False`.
        """
        for known in self.suggestions:
            if (
                known.line_end == suggestion.line_end
                and known.line_start == suggestion.line_start
            ):
                known.comment += f"\n{suggestion.comment}"
                return True
        return False

    def serialize_to_github_payload(self) -> Tuple[str, List[Dict[str, Any]]]:
        """Serialize this object into a summary and list of comments compatible
        with Github's REST API.

        :returns: The returned tuple contains a brief summary (at index ``0``)
            that contains markdown text describing the summary of the review
            comments.

            The list of `suggestions` (at index ``1``) is the serialized JSON
            object.
        """
        summary = ""
        comments = []
        posted_tool_advice = {"clang-tidy": 0, "clang-format": 0}
        for comment in self.suggestions:
            comments.append(comment.serialize_to_github_payload())
            if "### clang-format" in comment.comment:
                posted_tool_advice["clang-format"] += 1
            if "### clang-tidy" in comment.comment:
                posted_tool_advice["clang-tidy"] += 1

        for tool_name in ("clang-tidy", "clang-format"):
            if (
                len(comments)
                and posted_tool_advice[tool_name] != self.tool_total[tool_name]
            ):
                summary += (
                    f"Only {posted_tool_advice[tool_name]} out of "
                    + f"{self.tool_total[tool_name]} {tool_name}"
                    + " concerns fit within this pull request's diff.\n"
                )
            if self.full_patch[tool_name]:
                summary += (
                    f"\n<details><summary>Click here for the full {tool_name} patch"
                    + f"</summary>\n\n\n```diff\n{self.full_patch[tool_name]}\n"
                    + "```\n\n\n</details>\n\n"
                )
            elif not self.tool_total[tool_name]:
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

        return f"### {self.get_tool_name()} "

    def get_tool_name(self) -> str:
        """A function that must be implemented by derivatives to
        get the clang tool's name that generated the `patched` data."""

        raise NotImplementedError("must be implemented by derivative")

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
        tool_name = self.get_tool_name()
        assert tool_name in review_comments.full_patch
        review_comments.full_patch[tool_name] += f"{patch.text}"
        assert tool_name in review_comments.tool_total
        for hunk in patch.hunks:
            review_comments.tool_total[tool_name] += 1
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
                    line_numb = line.old_lineno
                    removed.append(line_numb)
            if not suggestion and removed:
                body += "\nPlease remove the line(s)\n- "
                body += "\n- ".join([str(x) for x in removed])
            else:
                body += f"\n```suggestion\n{suggestion}```"
            comment.comment = body
            if not review_comments.merge_similar_suggestion(comment):
                review_comments.suggestions.append(comment)
