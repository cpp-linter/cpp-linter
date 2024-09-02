"""A module to contain the abstractions about creating suggestions from a diff generated
by the clang tool's output."""

from abc import ABC
from typing import Optional, Dict, Any
from unidiff import PatchSet
from ..common_fs import FileObj


class PatchMixin(ABC):
    """An abstract mixin that unified parsing of the suggestions into
    PR review comments."""

    def __init__(self) -> None:
        #: A unified diff of the applied fixes from the clang tool's output
        self.patched: Optional[str] = None

    def get_suggestion_help(self, start, end) -> str:
        """Create helpful text about what the suggestion aims to fix."""

        raise NotImplementedError("derivative must implement this abstract method")

    def get_suggestions_from_patch(
        self,
        file_obj: FileObj,
        summary_only: bool,
    ):
        """Create a list of suggestions from the tool's `patched` output."""

        assert self.patched, f"No suggested patch found for {file_obj.name}"
        comments = []
        total = 0
        for hunk in PatchSet(self.patched)[0]:
            total += 1
            if summary_only:
                continue
            new_hunk_range = file_obj.is_hunk_contained(hunk)
            if new_hunk_range is None:
                continue
            start_line, end_line = new_hunk_range
            comment: Dict[str, Any] = {"path": file_obj.name}
            body = self.get_suggestion_help(start=start_line, end=end_line)
            if start_line < end_line:
                comment["start_line"] = start_line
            comment["line"] = end_line
            suggestion = ""
            removed = []
            for line in hunk:
                if line.line_type in ("+", " "):
                    suggestion += line.value
                else:
                    line_numb = line.source_line_no
                    assert line_numb is not None
                    removed.append(line_numb)
            if not suggestion and removed:
                body += "\nPlease remove the line(s)\n- "
                body += "\n- ".join([str(x) for x in removed])
            else:
                body += f"\n```suggestion\n{suggestion}```"
            comment["body"] = body
            comments.append(comment)
        return (self.patched, comments, total)
