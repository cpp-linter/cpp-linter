from concurrent.futures import ProcessPoolExecutor, as_completed
import json
from pathlib import Path
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
    db_json: Optional[List[Dict[str, str]]],
    format_cmd: Optional[str],
    format_filter: Optional[FormatFileFilter],
    tidy_filter: Optional[TidyFileFilter],
    args: Args,
) -> Tuple[str, str, Optional[TidyAdvice], Optional[FormatAdvice]]:
    log_stream = worker_log_init(log_lvl)

    tidy_note = None
    if tidy_cmd is not None and (
        tidy_filter is None or tidy_filter.is_source_or_ignored(file.name)
    ):
        tidy_note = run_clang_tidy(
            command=tidy_cmd,
            file_obj=file,
            checks=args.tidy_checks,
            lines_changed_only=args.lines_changed_only,
            database=args.database,
            extra_args=args.extra_arg,
            db_json=db_json,
            tidy_review=args.tidy_review,
            style=args.style,
        )

    format_advice = None
    if format_cmd is not None and (
        format_filter is None or format_filter.is_source_or_ignored(file.name)
    ):
        format_advice = run_clang_format(
            command=format_cmd,
            file_obj=file,
            style=args.style,
            lines_changed_only=args.lines_changed_only,
            format_review=args.format_review,
        )

    return file.name, log_stream.getvalue(), tidy_note, format_advice


def capture_clang_tools_output(files: List[FileObj], args: Args):
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
    if args.database:
        db = Path(args.database)
        if not db.is_absolute():
            args.database = str(db.resolve())
        db_path = (db / "compile_commands.json").resolve()
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
                db_json=db_json,
                format_cmd=format_cmd,
                format_filter=format_filter,
                tidy_filter=tidy_filter,
                args=args,
            )
            for file in files
        ]

        # temporary cache of parsed notifications for use in log commands
        for future in as_completed(futures):
            file_name, logs, tidy_advice, format_advice = future.result()

            start_log_group(f"Performing checkup on {file_name}")
            print(logs, flush=True)
            end_log_group()

            if tidy_advice or format_advice:
                for file in files:
                    if file.name == file_name:
                        if tidy_advice:
                            file.tidy_advice = tidy_advice
                        if format_advice:
                            file.format_advice = format_advice
                        break
                else:  # pragma: no cover
                    raise ValueError(f"Failed to find {file_name} in list of files.")
