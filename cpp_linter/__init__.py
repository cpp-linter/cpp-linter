"""Run clang-tidy and clang-format on a list of files.
If executed from command-line, then `main()` is the entrypoint.
"""
import json
import logging
import os
from .common_fs import list_source_files, CACHE_PATH
from .loggers import start_log_group, end_log_group, logger
from .clang_tools import capture_clang_tools_output
from .cli import cli_arg_parser, parse_ignore_option
from .rest_api.github_api import GithubApiClient


def main():
    """The main script."""

    # The parsed CLI args
    args = cli_arg_parser.parse_args()

    #  force files-changed-only to reflect value of lines-changed-only
    if args.lines_changed_only:
        args.files_changed_only = True

    rest_api_client = GithubApiClient()
    logger.info("processing %s event", rest_api_client.event_name)

    # set logging verbosity
    logger.setLevel(10 if args.verbosity or rest_api_client.debug_enabled else 20)

    # prepare ignored paths list
    ignored, not_ignored = parse_ignore_option(args.ignore, args.files)

    # change working directory
    os.chdir(args.repo_root)
    CACHE_PATH.mkdir(exist_ok=True)

    if logger.getEffectiveLevel() <= logging.DEBUG:
        start_log_group("Event json from the runner")
        logger.debug(json.dumps(rest_api_client.event_payload))
        end_log_group()

    if args.files_changed_only:
        files = rest_api_client.get_list_of_changed_files(
            args.extensions,
            ignored,
            not_ignored,
            args.lines_changed_only,
        )
        if files:
            rest_api_client.verify_files_are_present(files)
    else:
        files = list_source_files(args.extensions, ignored, not_ignored)
    if not files:
        logger.info("No source files need checking!")
    else:
        logger.info(
            "Giving attention to the following files:\n\t%s",
            "\n\t".join([f.name for f in files]),
        )
    end_log_group()

    (format_advice, tidy_advice) = capture_clang_tools_output(
        files,
        args.version,
        args.tidy_checks,
        args.style,
        args.lines_changed_only,
        args.database,
        args.extra_arg,
    )

    start_log_group("Posting comment(s)")
    rest_api_client.post_feedback(
        files,
        format_advice,
        tidy_advice,
        args.thread_comments,
        args.no_lgtm,
        args.step_summary,
        args.file_annotations,
        args.style,
    )
    end_log_group()


if __name__ == "__main__":
    main()
