"""Parse output from clang-tidy's stdout"""
from pathlib import Path, PurePath
import re
from typing import Tuple, Union, List, cast
from . import GlobalParser

NOTE_HEADER = re.compile(r"^(.*):(\d+):(\d+):\s(\w+):(.*)\[(.*)\]$")


class TidyNotification:
    """Create a object that decodes info from the clang-tidy output's initial line that
    details a specific notification.

    :param notification_line: The first line in the notification parsed into a
        `tuple` of `str` that represent the different components of the
        notification's details.
    """

    def __init__(
        self,
        notification_line: Tuple[str, Union[int, str], Union[int, str], str, str, str],
    ):
        # logger.debug("Creating tidy note from line %s", notification_line)
        (
            self.filename,
            self.line,
            #: The columns of the line that triggered the notification.
            self.cols,
            self.note_type,
            self.note_info,
            #: The clang-tidy check that enabled the notification.
            self.diagnostic,
        ) = notification_line

        #: The rationale of the notification.
        self.note_info = self.note_info.strip()
        #: The priority level of notification (warning/error).
        self.note_type = self.note_type.strip()
        #: The line number of the source file.
        self.line = int(self.line)
        self.cols = int(self.cols)
        #: The source filename concerning the notification.
        self.filename = (
            PurePath(self.filename).as_posix().replace(Path.cwd().as_posix(), "")
        )
        #: A `list` of lines for the code-block in the notification.
        self.fixit_lines: List[str] = []

    def __repr__(self) -> str:
        concerned_code = ""
        if self.fixit_lines:
            if not self.fixit_lines[-1].endswith("\n"):
                # some notifications' code-blocks don't end in a LF
                self.fixit_lines[-1] += "\n"  # and they should for us
            concerned_code = "```{}\n{}```\n".format(
                PurePath(self.filename).suffix.lstrip("."),
                "\n".join(self.fixit_lines),
            )
        return (
            "<details open>\n<summary><strong>{}:{}:{}:</strong> {}: [{}]"
            "\n\n> {}\n</summary><p>\n\n{}</p>\n</details>\n\n".format(
                self.filename,
                self.line,
                self.cols,
                self.note_type,
                self.diagnostic,
                self.note_info,
                concerned_code,
            )
        )

    def log_command(self) -> str:
        """Output the notification as a github log command.

        .. seealso::

            - `An error message <https://docs.github.com/en/actions/learn-github-
              actions/workflow-commands-for-github-actions#setting-an-error-message>`_
            - `A warning message <https://docs.github.com/en/actions/learn-github-
              actions/workflow-commands-for-github-actions#setting-a-warning-message>`_
            - `A notice message <https://docs.github.com/en/actions/learn-github-
              actions/workflow-commands-for-github-actions#setting-a-notice-message>`_
        """
        filename = self.filename.replace("\\", "/")
        return (
            "::{} file={file},line={line},title={file}:{line}:{cols} [{diag}]::"
            "{info}".format(
                "notice" if self.note_type.startswith("note") else self.note_type,
                file=filename,
                line=self.line,
                cols=self.cols,
                diag=self.diagnostic,
                info=self.note_info,
            )
        )


def parse_tidy_output() -> None:
    """Parse clang-tidy output in a file created from stdout. The results are
    saved to :attr:`~cpp_linter.GlobalParser.tidy_notes`."""
    notification = None
    tidy_out = Path("clang_tidy_report.txt").read_text(encoding="utf-8")
    for line in tidy_out.splitlines():
        match = re.match(NOTE_HEADER, line)
        if match is not None:
            notification = TidyNotification(
                cast(
                    Tuple[str, Union[int, str], Union[int, str], str, str, str],
                    match.groups(),
                )
            )
            GlobalParser.tidy_notes.append(notification)
        elif notification is not None:
            # append lines of code that are part of
            # the previous line's notification
            notification.fixit_lines.append(line)
