from functools import partial
import json
from multiprocessing import Pool
from pathlib import Path, PurePath
import subprocess
import sys
from tempfile import TemporaryDirectory
from textwrap import indent
from typing import Optional, List, Dict, Tuple
import shutil

from ..common_fs import FileObj
from ..loggers import start_log_group, end_log_group, worker_logfile, logger
from .clang_tidy import run_clang_tidy, TidyAdvice
from .clang_format import run_clang_format, FormatAdvice


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


def run_on_single_file(
    file: FileObj,
    tempdir: str,
    tidy_cmd,
    checks,
    lines_changed_only,
    database,
    extra_args,
    db_json,
    tidy_review,
    format_cmd,
    style,
    format_review,
):
    logfile = worker_logfile(tempdir)

    start_log_group(f"Performing checkup on {file.name}")

    tidy_note = None
    if tidy_cmd is not None:
        tidy_note = run_clang_tidy(
            tidy_cmd,
            file,
            checks,
            lines_changed_only,
            database,
            extra_args,
            db_json,
            tidy_review,
        )

    format_advice = None
    if format_cmd is not None:
        format_advice = run_clang_format(
            format_cmd, file, style, lines_changed_only, format_review
        )

    end_log_group()

    return logfile, tidy_note, format_advice


def capture_clang_tools_output(
    files: List[FileObj],
    version: str,
    checks: str,
    style: str,
    lines_changed_only: int,
    database: str,
    extra_args: List[str],
    tidy_review: bool,
    format_review: bool,
    num_workers: int,
) -> Tuple[List[FormatAdvice], List[TidyAdvice]]:
    """Execute and capture all output from clang-tidy and clang-format. This aggregates
    results in the :attr:`~cpp_linter.Globals.OUTPUT`.

    :param files: A list of files to analyze.
    :param version: The version of clang-tidy to run.
    :param checks: The `str` of comma-separated regulate expressions that describe
        the desired clang-tidy checks to be enabled/configured.
    :param style: The clang-format style rules to adhere. Set this to 'file' to
        use the relative-most .clang-format configuration file.
    :param lines_changed_only: A flag that forces focus on only changes in the event's
        diff info.
    :param database: The path to the compilation database.
    :param extra_args: A list of extra arguments used by clang-tidy as compiler
        arguments.
    :param tidy_review: A flag to enable/disable creating a diff suggestion for
        PR review comments using clang-tidy.
    :param format_review: A flag to enable/disable creating a diff suggestion for
        PR review comments using clang-format.
    """

    def show_tool_version_output(cmd: str):  # show version output for executable used
        version_out = subprocess.run(
            [cmd, "--version"], capture_output=True, check=True
        )
        logger.info("%s --version\n%s", cmd, indent(version_out.stdout.decode(), "\t"))

    tidy_cmd, format_cmd = (None, None)
    if style:  # if style is an empty value, then clang-format is skipped
        format_cmd = assemble_version_exec("clang-format", version)
        assert format_cmd is not None, "clang-format executable was not found"
        show_tool_version_output(format_cmd)
    if checks != "-*":  # if all checks are disabled, then clang-tidy is skipped
        tidy_cmd = assemble_version_exec("clang-tidy", version)
        assert tidy_cmd is not None, "clang-tidy executable was not found"
        show_tool_version_output(tidy_cmd)

    db_json: Optional[List[Dict[str, str]]] = None
    if database and not PurePath(database).is_absolute():
        database = str(Path(database).resolve())
    if database:
        db_path = Path(database, "compile_commands.json")
        if db_path.exists():
            db_json = json.loads(db_path.read_text(encoding="utf-8"))

    # temporary cache of parsed notifications for use in log commands
    tidy_notes = []
    format_advice = []
    with TemporaryDirectory() as tempdir, Pool(num_workers) as pool:
        results = pool.imap(
            partial(
                run_on_single_file,
                tempdir=tempdir,
                tidy_cmd=tidy_cmd,
                checks=checks,
                lines_changed_only=lines_changed_only,
                database=database,
                extra_args=extra_args,
                db_json=db_json,
                tidy_review=tidy_review,
                format_cmd=format_cmd,
                style=style,
                format_review=format_review,
            ),
            files,
        )

        for logfile, note, advice in results:
            sys.stdout.write(Path(logfile).read_text())
            if note is not None:
                tidy_notes.append(note)
            if advice is not None:
                format_advice.append(advice)

    return (format_advice, tidy_notes)
