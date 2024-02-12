"""Parse output from clang-tidy's stdout"""
import json
import os
from pathlib import Path, PurePath
import re
import subprocess
from typing import Tuple, Union, List, cast, Optional, Dict
from ..loggers import logger
from ..common_fs import FileObj

NOTE_HEADER = re.compile(r"^(.+):(\d+):(\d+):\s(\w+):(.*)\[([a-zA-Z\d\-\.]+)\]$")


class TidyNotification:
    """Create a object that decodes info from the clang-tidy output's initial line that
    details a specific notification.

    :param notification_line: The first line in the notification parsed into a
        `tuple` of `str` that represent the different components of the
        notification's details.
    :param database: The compilation database deserialized from JSON, only if
        :std:option:`--database` argument points to a valid path containing a
        ``compile_commands.json file``.
    """

    def __init__(
        self,
        notification_line: Tuple[str, Union[int, str], Union[int, str], str, str, str],
        database: Optional[List[Dict[str, str]]] = None,
    ):
        # logger.debug("Creating tidy note from line %s", notification_line)
        (
            self.filename,
            self.line,
            #: The columns of the line that triggered the notification.
            self.cols,
            self.severity,
            self.rationale,
            #: The clang-tidy check that enabled the notification.
            self.diagnostic,
        ) = notification_line

        #: The rationale of the notification.
        self.rationale = self.rationale.strip()
        #: The priority level of notification (warning/error).
        self.severity = self.severity.strip()
        #: The line number of the source file.
        self.line = int(self.line)
        self.cols = int(self.cols)
        rel_path = (
            Path(self.filename)
            .resolve()
            .as_posix()
            .replace(Path.cwd().as_posix() + "/", "")
        )
        if not PurePath(self.filename).is_absolute() and database is not None:
            # get absolute path from compilation database:
            # This is need for meson builds as they use paths relative to
            # the build env (or wherever the database is usually located).
            for unit in database:
                if (
                    "file" in unit
                    and "directory" in unit
                    and unit["file"] == self.filename
                ):
                    rel_path = (
                        Path(unit["directory"], unit["file"])
                        .resolve()
                        .as_posix()
                        .replace(Path.cwd().as_posix() + "/", "")
                    )
                    break
        #: The source filename concerning the notification.
        self.filename = rel_path
        #: A `list` of lines for the code-block in the notification.
        self.fixit_lines: List[str] = []

    @property
    def diagnostic_link(self) -> str:
        """Creates a markdown link to the diagnostic documentation."""
        link = f"[{self.diagnostic}](https://clang.llvm.org/extra/clang-tidy/checks/"
        return link + "{}/{}.html)".format(*self.diagnostic.split("-", maxsplit=1))

    def __repr__(self) -> str:
        return (
            f"<TidyNotification {self.filename}:{self.line}:{self.cols} "
            + f"{self.diagnostic}>"
        )


class TidyAdvice:
    def __init__(self, notes: List[TidyNotification]) -> None:
        #: A buffer of the applied fixes from clang-tidy
        self.patched: Optional[bytes] = None
        self.notes = notes

    def diagnostics_in_range(self, start: int, end: int) -> str:
        """Get a markdown formatted list of diagnostics found between a ``start``
        and ``end`` range of lines."""
        diagnostics = ""
        for note in self.notes:
            if note.line in range(start, end + 1):  # range is inclusive
                diagnostics += f"- {note.rationale} [{note.diagnostic_link}]\n"
        return diagnostics


def run_clang_tidy(
    command: str,
    file_obj: FileObj,
    checks: str,
    lines_changed_only: int,
    database: str,
    extra_args: List[str],
    db_json: Optional[List[Dict[str, str]]],
    tidy_review: bool,
) -> TidyAdvice:
    """Run clang-tidy on a certain file.

    :param command: The clang-tidy command to use (usually a resolved path).
    :param file_obj: Information about the `FileObj`.
    :param checks: The `str` of comma-separated regulate expressions that describe
        the desired clang-tidy checks to be enabled/configured.
    :param lines_changed_only: A flag that forces focus on only changes in the event's
        diff info.
    :param database: The path to the compilation database.
    :param extra_args: A list of extra arguments used by clang-tidy as compiler
        arguments.

        .. note::
            If the list is only 1 item long and there is a space in the first item,
            then the list is reformed from splitting the first item by whitespace
            characters.

            .. code-block:: shell

                cpp-linter --extra-arg="-std=c++14 -Wall"

            is equivalent to

            .. code-block:: shell

                cpp-linter --extra-arg=-std=c++14 --extra-arg=-Wall
    :param db_json: The compilation database deserialized from JSON, only if
        ``database`` parameter points to a valid path containing a
        ``compile_commands.json file``.
    :param tidy_review: A flag to enable/disable creating a diff suggestion for
        PR review comments.
    """
    filename = file_obj.name.replace("/", os.sep)
    cmds = [command]
    if checks:
        cmds.append(f"-checks={checks}")
    if database:
        cmds.append("-p")
        cmds.append(database)
    line_ranges = {
        "name": filename,
        "lines": file_obj.range_of_changed_lines(lines_changed_only, get_ranges=True),
    }
    if line_ranges["lines"]:
        # logger.info("line_filter = %s", json.dumps([line_ranges]))
        cmds.append(f"--line-filter={json.dumps([line_ranges])}")
    if len(extra_args) == 1 and " " in extra_args[0]:
        extra_args = extra_args[0].split()
    for extra_arg in extra_args:
        arg = extra_arg.strip('"')
        cmds.append(f'--extra-arg={arg}')
    cmds.append(filename)
    logger.info('Running "%s"', " ".join(cmds))
    results = subprocess.run(cmds, capture_output=True)
    logger.debug("Output from clang-tidy:\n%s", results.stdout.decode())
    if results.stderr:
        logger.debug(
            "clang-tidy made the following summary:\n%s", results.stderr.decode()
        )

    advice = parse_tidy_output(results.stdout.decode(), database=db_json)

    if tidy_review:
        # clang-tidy overwrites the file contents when applying fixes.
        # create a cache of original contents
        original_buf = Path(file_obj.name).read_bytes()
        cmds.insert(1, "--fix-errors")  # include compiler-suggested fixes
        # run clang-tidy again to apply any fixes
        logger.info('Getting fixes with "%s"', " ".join(cmds))
        subprocess.run(cmds, check=True)
        # store the modified output from clang-tidy
        advice.patched = Path(file_obj.name).read_bytes()
        # re-write original file contents
        Path(file_obj.name).write_bytes(original_buf)
    return advice


def parse_tidy_output(
    tidy_out: str, database: Optional[List[Dict[str, str]]]
) -> TidyAdvice:
    """Parse clang-tidy stdout.

    :param tidy_out: The stdout from clang-tidy.
    :param database: The compilation database deserialized from JSON, only if
        :std:option:`--database` argument points to a valid path containing a
        ``compile_commands.json file``.
    """
    notification = None
    tidy_notes = []
    for line in tidy_out.splitlines():
        match = re.match(NOTE_HEADER, line)
        if match is not None:
            notification = TidyNotification(
                cast(
                    Tuple[str, Union[int, str], Union[int, str], str, str, str],
                    match.groups(),
                ),
                database,
            )
            tidy_notes.append(notification)
        elif notification is not None:
            # append lines of code that are part of
            # the previous line's notification
            notification.fixit_lines.append(line)
    return TidyAdvice(notes=tidy_notes)