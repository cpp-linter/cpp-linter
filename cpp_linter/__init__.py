"""Run clang-tidy and clang-format on a list of files.
If executed from command-line, then `main()` is the entrypoint.
"""

import os
from .common_fs import CACHE_PATH
from .common_fs.file_filter import FileFilter
from .loggers import start_log_group, end_log_group, logger
from .clang_tools import capture_clang_tools_output
from .cli import get_cli_parser, Args
from .rest_api.github_api import GithubApiClient


def main():
    """The main script."""

    # The parsed CLI args
    args = get_cli_parser().parse_args(namespace=Args())

    #  force files-changed-only to reflect value of lines-changed-only
    if args.lines_changed_only:
        args.files_changed_only = True

    rest_api_client = GithubApiClient()
    logger.info("processing %s event", rest_api_client.event_name)
    is_pr_event = rest_api_client.event_name == "pull_request"
    if not is_pr_event:
        args.tidy_review = False
        args.format_review = False

    # set logging verbosity
    logger.setLevel(10 if args.verbosity or rest_api_client.debug_enabled else 20)

    # prepare ignored paths list
    global_file_filter = FileFilter(
        extensions=args.extensions, ignore_value=args.ignore, not_ignored=args.files
    )
    global_file_filter.parse_submodules()

    # change working directory
    os.chdir(args.repo_root)
    CACHE_PATH.mkdir(exist_ok=True)

    start_log_group("Get list of specified source files")
    if args.files_changed_only:
        files = rest_api_client.get_list_of_changed_files(
            file_filter=global_file_filter,
            lines_changed_only=args.lines_changed_only,
        )
        rest_api_client.verify_files_are_present(files)
    else:
        files = global_file_filter.list_source_files()
        # at this point, files have no info about git changes.
        # for PR reviews, we need this info
        if is_pr_event and (args.tidy_review or args.format_review):
            # get file changes from diff
            git_changes = rest_api_client.get_list_of_changed_files(
                file_filter=global_file_filter,
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

    capture_clang_tools_output(files=files, args=args)

    start_log_group("Posting comment(s)")
    rest_api_client.post_feedback(files=files, args=args)
    end_log_group()


if __name__ == "__main__":
    main()
