"""Run clang-tidy and clang-format on a list of files.
If executed from command-line, then `main()` is the entrypoint.
"""

import asyncio
import os

from ._version import version
from .clang_tools import capture_clang_tools_output
from .cli import Args, get_cli_parser
from .common_fs import CACHE_PATH
from .common_fs.file_filter import make_file_filter, list_source_files
from .loggers import end_log_group, logger, start_log_group
from .rest_api import LinterClient


async def run():
    """The main script."""

    # The parsed CLI args
    args = get_cli_parser().parse_args(namespace=Args())
    if args.command == "version":
        print(version)
        return

    #  force files-changed-only to reflect value of lines-changed-only
    if args.lines_changed_only:
        args.files_changed_only = True

    client = LinterClient()
    logger.info("processing %s event", client.event_name)
    is_pr_event = client.is_pr_event

    if not is_pr_event:
        args.tidy_review = False
        args.format_review = False

    # set logging verbosity
    logger.setLevel(10 if args.verbosity or client.debug_enabled else 20)

    # prepare ignored paths list
    global_file_filter = make_file_filter(
        extensions=args.extensions, ignore_value=args.ignore, not_ignored=args.files
    )
    global_file_filter.parse_submodules()

    # change working directory
    os.chdir(args.repo_root)
    CACHE_PATH.mkdir(exist_ok=True)

    start_log_group("Get list of specified source files")
    if args.files_changed_only:
        files = await client.get_changed_files(
            file_filter=global_file_filter,
            lines_changed_only=args.lines_changed_only,
            diff_base=args.diff_base,
            ignore_index=args.ignore_index,
        )
    else:
        files = list_source_files(global_file_filter)
        # at this point, files have no info about git changes.
        # for PR reviews, we need this info
        if is_pr_event and (args.tidy_review or args.format_review):
            # get file changes from diff
            git_changes = await client.get_changed_files(
                file_filter=global_file_filter,
                lines_changed_only=0,  # prevent filtering out unchanged files
                diff_base=args.diff_base,
                ignore_index=args.ignore_index,
            )
            # merge info from git changes into list of all files
            for git_file in git_changes:
                for file in files:
                    if git_file.name == file.name:
                        file.additions = git_file.additions
                        file.diff_chunks = git_file.diff_chunks
                        file.lines_added = git_file.lines_added
                        break
    if not files:
        logger.info("No source files need checking!")
    else:
        logger.info(
            "Giving attention to the following files:\n\t%s",
            "\n\t".join([f.name for f in files]),
        )
    end_log_group()

    clang_versions = capture_clang_tools_output(files=files, args=args)

    start_log_group("Posting comment(s)")
    await client.post_feedback(files=files, args=args, clang_versions=clang_versions)
    end_log_group()


def main():
    """The command line entrypoint."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
