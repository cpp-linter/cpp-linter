"""A module for running outside GitHub Actions.

This covers a developer's machine and other CI systems, such as GitLab CI or
Jenkins. Nothing is posted to a git server.
"""

from pathlib import Path

from ..common_fs import FileObj
from ..common_fs.file_filter import FileFilter
from ..clang_tools.clang_format import formalize_style_name, tally_format_advice
from ..clang_tools.clang_tidy import tally_tidy_advice
from ..clang_tools import ClangVersions
from ..cli import Args
from ..loggers import logger, log_commander
from ..git import parse_diff, get_diff
from . import RestApiClient, RateLimitHeaders

#: No REST API is used, so there are no rate limit headers to read.
RATE_LIMIT_HEADERS = RateLimitHeaders(reset="", remaining="", retry="")


class LocalApiClient(RestApiClient):
    """A client used when cpp-linter is not running in GitHub Actions.

    Changed files come from the local git repository (see the ``--diff-base`` option),
    and feedback is only written to the log and to the ``--summary-output-file``.
    """

    def __init__(self) -> None:
        super().__init__(rate_limit_headers=RATE_LIMIT_HEADERS)
        self._name = "Local"
        self.event_name = "local"

    def get_list_of_changed_files(
        self,
        file_filter: FileFilter,
        lines_changed_only: int,
        diff_base: None | int | str = None,
        ignore_index: bool = False,
    ) -> list[FileObj]:
        return parse_diff(
            get_diff(diff_base, ignore_index), file_filter, lines_changed_only
        )

    def post_feedback(
        self,
        files: list[FileObj],
        args: Args,
        clang_versions: ClangVersions,
    ):
        format_checks_failed = tally_format_advice(files)
        tidy_checks_failed = tally_tidy_advice(files)

        if args.summary_output_file:
            comment = self.make_comment(
                files=files,
                format_checks_failed=format_checks_failed,
                tidy_checks_failed=tidy_checks_failed,
                clang_versions=clang_versions,
                len_limit=None,
            )
            summary_output_path = Path(args.summary_output_file).resolve()
            try:
                summary_output_path.parent.mkdir(parents=True, exist_ok=True)
                summary_output_path.write_text(f"\n{comment}\n", encoding="utf-8")
            except (OSError, ValueError) as e:
                log_commander.error(
                    "Failed to write summary output file '%s': %s",
                    summary_output_path,
                    e,
                )

        if args.file_annotations:
            self.make_annotations(files=files, style=args.style)

        self.set_exit_code(
            checks_failed=format_checks_failed + tidy_checks_failed,
            format_checks_failed=format_checks_failed,
            tidy_checks_failed=tidy_checks_failed,
        )

        if args.thread_comments != "false":
            logger.warning(
                "Thread comments are only posted when running in GitHub Actions."
            )

    @staticmethod
    def make_annotations(files: list[FileObj], style: str) -> None:
        """Print each finding as a plain log line, in the format compilers use.

        :param files: A list of objects, each describing a file's information.
        :param style: The chosen code style guidelines. The value 'file' is replaced
            with 'custom style'.
        """
        style_guide = formalize_style_name(style)
        for file_obj in files:
            if file_obj.format_advice and file_obj.format_advice.replaced_lines:
                lines = ", ".join(
                    str(fix.line) for fix in file_obj.format_advice.replaced_lines
                )
                log_commander.info(
                    "%s: does not conform to %s style guidelines (lines %s)",
                    file_obj.name,
                    style_guide,
                    lines,
                )
        for file_obj in files:
            if not file_obj.tidy_advice:
                continue
            for note in file_obj.tidy_advice.notes:
                if note.filename == file_obj.name:
                    log_commander.info(
                        "%s:%d:%d: %s: %s [%s]",
                        file_obj.name,
                        note.line,
                        note.cols,
                        note.severity,
                        note.rationale,
                        note.diagnostic,
                    )
