from abc import ABC
from pathlib import PurePath
import requests
from typing import Optional, Dict, List, Tuple
from ..common_fs import FileObj
from ..clang_tools.clang_format import FormatAdvice
from ..clang_tools.clang_tidy import TidyAdvice
from ..loggers import logger


USER_OUTREACH = (
    "\n\nHave any feedback or feature suggestions? [Share it here.]"
    + "(https://github.com/cpp-linter/cpp-linter-action/issues)"
)
COMMENT_MARKER = "<!-- cpp linter action -->\n"


class RestApiClient(ABC):
    def __init__(self) -> None:
        self.session = requests.Session()

    def set_exit_code(
        self,
        checks_failed: int,
        format_checks_failed: Optional[int] = None,
        tidy_checks_failed: Optional[int] = None,
    ):
        """Set the action's output values and shows them in the log output.

        :param checks_failed: A int describing the total number of checks that failed.
        :param format_checks_failed: A int describing the number of checks that failed
            only for clang-format.
        :param tidy_checks_failed: A int describing the number of checks that failed
            only for clang-tidy.

        :returns:
            The ``checks_failed`` parameter was not passed.
        """
        logger.info("%d clang-format-checks-failed", format_checks_failed or 0)
        logger.info("%d clang-tidy-checks-failed", tidy_checks_failed or 0)
        logger.info("%d checks-failed", checks_failed)
        return checks_failed

    def make_headers(self, use_diff: bool = False) -> Dict[str, str]:
        """Create a `dict` for use in REST API headers.

        :param use_diff: A flag to indicate that the returned format should be in diff
            syntax.
        :returns: A `dict` to be used as headers in `requests` API calls.
        """
        raise NotImplementedError("must be implemented in the derivative")

    def get_list_of_changed_files(
        self,
        extensions: List[str],
        ignored: List[str],
        not_ignored: List[str],
        lines_changed_only: int,
    ) -> List[FileObj]:
        """Fetch a list of the event's changed files.

        :param extensions: A list of file extensions to focus on only.
        :param ignored: A list of paths or files to ignore.
        :param not_ignored: A list of paths or files to explicitly not ignore.
        :param lines_changed_only: A value that dictates what file changes to focus on.
        """
        raise NotImplementedError("must be implemented in the derivative")

    @staticmethod
    def make_comment(
        files: List[FileObj],
        format_advice: List[FormatAdvice],
        tidy_advice: List[TidyAdvice],
    ) -> Tuple[str, int, int]:
        """Make an MarkDown comment from the given advice. Also returns a count of
        checks failed for each tool (clang-format and clang-tidy)

        :param files: A list of objects, each describing a file's information.
        :param format_advice: A list of clang-format advice parallel to the list of
            ``files``.
        :param tidy_advice: A list of clang-tidy advice parallel to the list of
            ``files``.

        :Returns: A `tuple` in which the items correspond to

            - The markdown comment as a `str`
            - The tally of ``format_checks_failed`` as an `int`
            - The tally of ``tidy_checks_failed`` as an `int`
        """
        format_comment = ""
        format_checks_failed, tidy_checks_failed = (0, 0)
        for file_obj, advice in zip(files, format_advice):
            if advice.replaced_lines:
                format_comment += f"- {file_obj.name}\n"
                format_checks_failed += 1

        tidy_comment = ""
        for file_obj, concern in zip(files, tidy_advice):
            for note in concern.notes:
                if file_obj.name == note.filename:
                    tidy_comment += "- **{filename}:{line}:{cols}:** ".format(
                        filename=file_obj.name,
                        line=note.line,
                        cols=note.cols,
                    )
                    tidy_comment += (
                        "{severity}: [{diagnostic}]\n   > {rationale}\n".format(
                            severity=note.severity,
                            diagnostic=note.diagnostic_link,
                            rationale=note.rationale,
                        )
                    )
                    if note.fixit_lines:
                        ext = PurePath(file_obj.name).suffix.lstrip(".")
                        suggestion = "\n   ".join(note.fixit_lines)
                        tidy_comment += f"\n   ```{ext}\n   {suggestion}\n   ```\n"
                    tidy_checks_failed += 1
                else:
                    logger.debug("%s != %s", file_obj.name, note.filename)

        comment = f"{COMMENT_MARKER}# Cpp-Linter Report "
        if format_comment or tidy_comment:
            comment += ":warning:\nSome files did not pass the configured checks!\n"
            if format_comment:
                comment += "\n<details><summary>clang-format reports: <strong>"
                comment += f"{format_checks_failed} file(s) not formatted</strong>"
                comment += f"</summary>\n\n{format_comment}\n</details>"
            if tidy_comment:
                comment += "\n<details><summary>clang-tidy reports: <strong>"
                comment += f"{tidy_checks_failed} concern(s)</strong></summary>\n\n"
                comment += f"{tidy_comment}\n</details>"
        else:
            comment += ":heavy_check_mark:\nNo problems need attention."
        comment += USER_OUTREACH
        return (comment, format_checks_failed, tidy_checks_failed)

    def post_feedback(
        self,
        files: List[FileObj],
        format_advice: List[FormatAdvice],
        tidy_advice: List[TidyAdvice],
        thread_comments: str,
        no_lgtm: bool,
        step_summary: bool,
        file_annotations: bool,
        style: str,
        tidy_review: bool,
        format_review: bool,
    ):
        """Post action's results using REST API.

        :param files: A list of objects, each describing a file's information.
        :param format_advice: A list of clang-format advice parallel to the list of
            ``files``.
        :param tidy_advice: A list of clang-tidy advice parallel to the list of
            ``files``.
        :param thread_comments: A flag that describes if how thread comments should
            be handled. See :std:option:`--thread-comments`.
        :param no_lgtm: A flag to control if a "Looks Good To Me" comment should be
            posted. If this is `False`, then an outdated bot comment will still be
            deleted. See :std:option:`--no-lgtm`.
        :param step_summary: A flag that describes if a step summary should
            be posted. See :std:option:`--step-summary`.
        :param file_annotations: A flag that describes if file annotations should
            be posted. See :std:option:`--file-annotations`.
        :param style: The style used for clang-format. See :std:option:`--style`.
        :param tidy_review: A flag to enable/disable creating a diff suggestion for
            PR review comments using clang-tidy.
        :param format_review: A flag to enable/disable creating a diff suggestion for
            PR review comments using clang-format.
        """
        raise NotImplementedError("Must be defined in the derivative")
