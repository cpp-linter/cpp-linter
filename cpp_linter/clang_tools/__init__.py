from concurrent.futures import ProcessPoolExecutor, as_completed
import json
from pathlib import Path, PurePath
import subprocess
from textwrap import indent
from typing import Optional, List, Dict, Tuple
import shutil

from ..common_fs import FileObj
from ..common_fs.file_filter import TidyFileFilter, FormatFileFilter
from ..loggers import start_log_group, end_log_group, worker_log_init, logger
from .clang_tidy import run_clang_tidy, TidyAdvice
from .clang_format import run_clang_format, FormatAdvice
from ..cli import Args


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


def _run_on_single_file(
    file: FileObj,
    log_lvl: int,
    tidy_cmd: Optional[str],
    checks: str,
    lines_changed_only: int,
    database: str,
    extra_args: List[str],
    db_json: Optional[List[Dict[str, str]]],
    tidy_review: bool,
    format_cmd: Optional[str],
    style: str,
    format_review: bool,
    format_filter: Optional[FormatFileFilter],
    tidy_filter: Optional[TidyFileFilter],
):
    log_stream = worker_log_init(log_lvl)

    tidy_note = None
    if tidy_cmd is not None and (
        tidy_filter is None or tidy_filter.is_source_or_ignored(file.name)
    ):
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
    if format_cmd is not None and (
        format_filter is None or format_filter.is_source_or_ignored(file.name)
    ):
        format_advice = run_clang_format(
            format_cmd, file, style, lines_changed_only, format_review
        )

    return file.name, log_stream.getvalue(), tidy_note, format_advice


def capture_clang_tools_output(
    files: List[FileObj],
    args: Args,
) -> Tuple[List[FormatAdvice], List[TidyAdvice]]:
    """Execute and capture all output from clang-tidy and clang-format. This aggregates
    results in the :attr:`~cpp_linter.Globals.OUTPUT`.

    :param files: A list of files to analyze.
    :param args: A namespace of parsed args from the :doc:`CLI <../cli_args>`.
    """

    def show_tool_version_output(cmd: str):  # show version output for executable used
        version_out = subprocess.run(
            [cmd, "--version"], capture_output=True, check=True
        )
        logger.info("%s --version\n%s", cmd, indent(version_out.stdout.decode(), "\t"))

    tidy_cmd, format_cmd = (None, None)
    tidy_filter, format_filter = (None, None)
    if args.style:  # if style is an empty value, then clang-format is skipped
        format_cmd = assemble_version_exec("clang-format", args.version)
        assert format_cmd is not None, "clang-format executable was not found"
        show_tool_version_output(format_cmd)
        tidy_filter = TidyFileFilter(
            extensions=args.extensions,
            ignore_value=args.ignore_tidy,
        )
    if args.tidy_checks != "-*":
        # if all checks are disabled, then clang-tidy is skipped
        tidy_cmd = assemble_version_exec("clang-tidy", args.version)
        assert tidy_cmd is not None, "clang-tidy executable was not found"
        show_tool_version_output(tidy_cmd)
        format_filter = FormatFileFilter(
            extensions=args.extensions,
            ignore_value=args.ignore_format,
        )

    db_json: Optional[List[Dict[str, str]]] = None
    if args.database and not PurePath(args.database).is_absolute():
        args.database = str(Path(args.database).resolve())
    if args.database:
        db_path = Path(args.database, "compile_commands.json")
        if db_path.exists():
            db_json = json.loads(db_path.read_text(encoding="utf-8"))

    with ProcessPoolExecutor(args.jobs) as executor:
        log_lvl = logger.getEffectiveLevel()
        futures = [
            executor.submit(
                _run_on_single_file,
                file,
                log_lvl=log_lvl,
                tidy_cmd=tidy_cmd,
                checks=args.tidy_checks,
                lines_changed_only=args.lines_changed_only,
                database=args.database,
                extra_args=args.extra_arg,
                db_json=db_json,
                tidy_review=args.tidy_review,
                format_cmd=format_cmd,
                style=args.style,
                format_review=args.format_review,
                format_filter=format_filter,
                tidy_filter=tidy_filter,
            )
            for file in files
        ]

        # temporary cache of parsed notifications for use in log commands
        format_advice_map: Dict[str, Optional[FormatAdvice]] = {}
        tidy_notes_map: Dict[str, Optional[TidyAdvice]] = {}
        for future in as_completed(futures):
            file, logs, note, advice = future.result()

            start_log_group(f"Performing checkup on {file}")
            print(logs, flush=True)
            end_log_group()

            format_advice_map[file] = advice
            tidy_notes_map[file] = note

    format_advice = list(filter(None, (format_advice_map[file.name] for file in files)))
    tidy_notes = list(filter(None, (tidy_notes_map[file.name] for file in files)))

    return (format_advice, tidy_notes)
