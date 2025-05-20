"""A module to contain the abstractions about creating suggestions from a diff generated
by the clang tool's output."""

from abc import ABC
from typing import Optional, Dict, Any, List, Tuple
from pygit2 import Patch  # type: ignore
from ..common_fs import FileObj
from pygit2.enums import DiffOption  # type: ignore

INDENT_HEURISTIC = DiffOption.INDENT_HEURISTIC


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
        from ..rest_api import COMMENT_MARKER  # workaround circular import

        result = {
            "path": self.file_name,
            "body": f"{COMMENT_MARKER}{self.comment}",
            "line": self.line_end,
        }
        if self.line_start != self.line_end and self.line_start > 0:
            result["start_line"] = self.line_start
        return result


class ReviewComments:
    """A data structure to contain PR review comments from a specific clang tool."""

    def __init__(self) -> None:
        #: The list of actual comments
        self.suggestions: List[Suggestion] = []

        self.tool_total: Dict[str, Optional[int]] = {
            "clang-tidy": None,
            "clang-format": None,
        }
        """The total number of concerns about a specific clang tool.

        This may not equate to the length of `suggestions` because
        1. There is no guarantee that all suggestions will fit within the PR's diff.
        2. Suggestions are a combined result of advice from both tools.

        A `None` value means a review was not requested from the corresponding tool.
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
                known.file_name == suggestion.file_name
                and known.line_end == suggestion.line_end
                and known.line_start == suggestion.line_start
            ):
                known.comment += f"\n{suggestion.comment}"
                return True
        return False

    def serialize_to_github_payload(
        # avoid circular imports by accepting primitive types (instead of ClangVersions)
        self,
        tidy_version: Optional[str],
        format_version: Optional[str],
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Serialize this object into a summary and list of comments compatible
        with Github's REST API.

        :param tidy_version: The version numbers of the clang-tidy used.
        :param format_version: The version numbers of the clang-format used.

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
            tool_version = tidy_version
            if tool_name == "clang-format":
                tool_version = format_version
            if tool_version is None or self.tool_total[tool_name] is None:
                continue  # if tool wasn't used
            summary += f"### Used {tool_name} v{tool_version}\n\n"
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
        return (summary, comments)


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
        assert self.patched, (
            f"{self.__class__.__name__} has no suggestions for {file_obj.name}"
        )
        patch = Patch.create_from(
            file_obj.read_with_timeout(),
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
        tool_total = review_comments.tool_total[tool_name] or 0
        for hunk in patch.hunks:
            tool_total += 1
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

        review_comments.tool_total[tool_name] = tool_total
