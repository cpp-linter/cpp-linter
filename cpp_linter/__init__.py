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
    is_pr_event = rest_api_client.event_name == "pull_request"

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
            extensions=args.extensions,
            ignored=ignored,
            not_ignored=not_ignored,
            lines_changed_only=args.lines_changed_only,
        )
        rest_api_client.verify_files_are_present(files)
    else:
        files = list_source_files(args.extensions, ignored, not_ignored)
        # at this point, files have no info about git changes.
        # for PR reviews, we need this info
        if is_pr_event and (args.tidy_review or args.format_review):
            # get file changes from diff
            git_changes = rest_api_client.get_list_of_changed_files(
                extensions=args.extensions,
                ignored=ignored,
                not_ignored=not_ignored,
                lines_changed_only=0,  # prevent filtering out unchanged files
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

    (format_advice, tidy_advice) = capture_clang_tools_output(
        files=files,
        version=args.version,
        checks=args.tidy_checks,
        style=args.style,
        lines_changed_only=args.lines_changed_only,
        database=args.database,
        extra_args=args.extra_arg,
        tidy_review=is_pr_event and args.tidy_review,
        format_review=is_pr_event and args.format_review,
    )

    start_log_group("Posting comment(s)")
    rest_api_client.post_feedback(
        files=files,
        format_advice=format_advice,
        tidy_advice=tidy_advice,
        thread_comments=args.thread_comments,
        no_lgtm=args.no_lgtm,
        step_summary=args.step_summary,
        file_annotations=args.file_annotations,
        style=args.style,
        tidy_review=args.tidy_review,
        format_review=args.format_review,
    )
    end_log_group()


if __name__ == "__main__":
    main()
