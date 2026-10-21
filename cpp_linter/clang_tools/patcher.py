"""A module to contain the abstractions about creating suggestions from a diff generated
by the clang tool's output."""

import io
import os
import re
import shutil
import subprocess
import tempfile
from abc import ABC
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..common_fs import FileObj

#: Matches a unified diff hunk header, e.g. ``@@ -3,2 +3 @@``.
HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class DiffLine:
    """A single line of a `DiffHunk`."""

    #: ``"+"`` for an added line or ``"-"`` for a removed line.
    origin: str
    #: The line's text, including its line ending (if any).
    content: str
    #: The line number in the original file (``-1`` for added lines).
    old_lineno: int


@dataclass
class DiffHunk:
    """A hunk of a unified diff generated without context lines."""

    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    lines: list[DiffLine] = field(default_factory=list)


@dataclass
class Patch:
    """A unified diff of a file's original content and a clang tool's fixes."""

    #: The diff as text (shown in the PR review summary).
    text: str
    #: The parsed hunks of the diff.
    hunks: list[DiffHunk]

    @classmethod
    def create_from(cls, old: Path, new: bytes, file_name: str) -> "Patch":
        """Diff the ``old`` file against the ``new`` content with ``git diff``.

        This uses the same diff algorithm (and indent heuristic) as libgit2, so hunks
        are the same as the ones pygit2 produced before it was dropped.
        """
        git = shutil.which("git")
        if git is None:
            raise FileNotFoundError("git is required to create PR review suggestions")
        # resolve symlinks; git would diff a symlink's target path, not its content
        old_path = old.resolve()
        with tempfile.TemporaryDirectory() as tmp:
            new_path = Path(tmp, "new")
            new_path.write_bytes(new)
            result = subprocess.run(
                [
                    git,
                    "diff",
                    "--no-index",
                    "--no-color",
                    "--no-ext-diff",
                    "--text",
                    "--indent-heuristic",
                    "--unified=0",
                    str(old_path),
                    new_path.name,
                ],
                capture_output=True,
                check=False,
                # Keep the user's repo (.gitattributes) and git config out of the diff,
                # e.g. `text=auto` would otherwise hide CRLF -> LF changes.
                cwd=tmp,
                env={
                    # drop inherited GIT_* settings (GIT_DIR, GIT_CONFIG_COUNT, ...)
                    **{
                        k: v
                        for k, v in os.environ.items()
                        if not k.startswith("GIT_") or k == "GIT_EXEC_PATH"
                    },
                    "GIT_CEILING_DIRECTORIES": str(Path(tmp).parent),
                    "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_CONFIG_GLOBAL": os.devnull,
                },
            )
        # `git diff --no-index` exits with 1 when the files differ, but also when it
        # cannot read a file (then it prints nothing to stdout).
        if result.returncode not in (0, 1) or (
            result.returncode == 1 and not result.stdout
        ):
            raise RuntimeError(
                f"git diff failed for {file_name}: "
                + result.stderr.decode(errors="replace")
            )
        return cls.parse(
            result.stdout.decode(encoding="utf-8", errors="replace"), file_name
        )

    @classmethod
    def parse(cls, diff: str, file_name: str) -> "Patch":
        """Parse the output of ``git diff --unified=0`` for a single file."""
        # split on "\n" only; str.splitlines() would also split on "\r", "\f", etc.
        lines = list(io.StringIO(diff, newline="\n"))
        first_hunk = next(
            (i for i, line in enumerate(lines) if line.startswith("@@")), len(lines)
        )
        text = ""
        if first_hunk < len(lines):
            text = (
                f"diff --git a/{file_name} b/{file_name}\n"
                + f"--- a/{file_name}\n+++ b/{file_name}\n"
                + "".join(lines[first_hunk:])
            )
        hunks: list[DiffHunk] = []
        old_lineno = 0
        for line in lines[first_hunk:]:
            header = HUNK_HEADER.match(line)
            if header is not None:
                old_start, old_lines, new_start, new_lines = header.groups()
                hunks.append(
                    DiffHunk(
                        old_start=int(old_start),
                        old_lines=1 if old_lines is None else int(old_lines),
                        new_start=int(new_start),
                        new_lines=1 if new_lines is None else int(new_lines),
                    )
                )
                old_lineno = int(old_start)
            elif hunks and line.startswith("-"):
                hunks[-1].lines.append(DiffLine("-", line[1:], old_lineno))
                old_lineno += 1
            elif hunks and line.startswith("+"):
                hunks[-1].lines.append(DiffLine("+", line[1:], -1))
            elif hunks and hunks[-1].lines and line.startswith("\\"):
                # "\ No newline at end of file": the previous line has no newline
                prev = hunks[-1].lines[-1]
                prev.content = prev.content.removesuffix("\n")
        return cls(text=text, hunks=hunks)


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

    def serialize_to_github_payload(self) -> dict[str, Any]:
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
        self.suggestions: list[Suggestion] = []

        self.tool_total: dict[str, int | None] = {
            "clang-tidy": None,
            "clang-format": None,
        }
        """The total number of concerns about a specific clang tool.

        This may not equate to the length of `suggestions` because
        1. There is no guarantee that all suggestions will fit within the PR's diff.
        2. Suggestions are a combined result of advice from both tools.

        A `None` value means a review was not requested from the corresponding tool.
        """

        self.full_patch: dict[str, str] = {"clang-tidy": "", "clang-format": ""}
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
        tidy_version: str | None,
        format_version: str | None,
        reused: int = 0,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Serialize this object into a summary and list of comments compatible
        with Github's REST API.

        :param tidy_version: The version numbers of the clang-tidy used.
        :param format_version: The version numbers of the clang-format used.
        :param reused: The number of review comments that were already posted
            (in a previous review) and thus culled from the new review. This is
            only used to add a note to the summary.

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
        if reused > 0:
            summary += (
                f"\n{reused} review comment(s) from a previous review "
                + "were reused (not posted again).\n"
            )
        return (summary, comments)


class PatchMixin(ABC):
    """An abstract mixin that unified parsing of the suggestions into
    PR review comments."""

    def __init__(self) -> None:
        #: A unified diff of the applied fixes from the clang tool's output
        self.patched: bytes | None = None

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
        self,
        file_obj: FileObj,
        summary_only: bool,
        review_comments: ReviewComments,
        repo_root: str,
    ):
        """Create a list of suggestions from the tool's `patched` output.

        Results are stored in the ``review_comments`` parameter (passed by reference).
        The file's name is relative to ``repo_root``.
        """
        assert self.patched, (
            f"{self.__class__.__name__} has no suggestions for {file_obj.name}"
        )
        patch = Patch.create_from(
            Path(repo_root, file_obj.name), self.patched, file_obj.name
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
