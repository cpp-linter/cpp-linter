"""Run clang-tidy and clang-format on a list of changed files provided by GitHub's
REST API. If executed from command-line, then `main()` is the entrypoint.

.. seealso::

    - `github rest API reference for pulls <https://docs.github.com/en/rest/pulls>`_
    - `github rest API reference for commits <https://docs.github.com/en/rest/commits>`_
    - `github rest API reference for repos <https://docs.github.com/en/rest/repos>`_
    - `github rest API reference for issues <https://docs.github.com/en/rest/issues>`_
"""
import subprocess
from pathlib import Path, PurePath
import os
import sys
import configparser
import json
import urllib.parse
import logging
from typing import cast, List, Dict, Any, Tuple, Optional
import requests
from . import (
    Globals,
    GlobalParser,
    logger,
    GITHUB_TOKEN,
    GITHUB_SHA,
    make_headers,
    IS_ON_RUNNER,
    CACHE_PATH,
    CLANG_FORMAT_XML,
    CLANG_TIDY_YML,
    CLANG_TIDY_STDOUT,
    CHANGED_FILES_JSON,
    log_response_msg,
    range_of_changed_lines,
    assemble_version_exec,
)
from .clang_tidy_yml import parse_tidy_suggestions_yml
from .clang_format_xml import parse_format_replacements_xml
from .clang_tidy import parse_tidy_output, TidyNotification
from .thread_comments import remove_bot_comments, list_diff_comments  # , get_review_id
from .git import get_diff, parse_diff
from .cli import cli_arg_parser

# global constant variables
GITHUB_EVENT_PATH = os.getenv("GITHUB_EVENT_PATH", "")
GITHUB_API_URL = os.getenv("GITHUB_API_URL", "https://api.github.com")
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "")
GITHUB_EVENT_NAME = os.getenv("GITHUB_EVENT_NAME", "unknown")
GITHUB_WORKSPACE = os.getenv("GITHUB_WORKSPACE", "")
IS_USING_DOCKER = os.getenv("USING_CLANG_TOOLS_DOCKER", os.getenv("CLANG_VERSIONS"))
RUNNER_WORKSPACE = "/github/workspace" if IS_USING_DOCKER else GITHUB_WORKSPACE


def set_exit_code(override: Optional[int] = None) -> int:
    """Set the action's exit code.

    :param override: The number to use when overriding the action's logic.

    :returns:
        The exit code that was used. If the ``override`` parameter was not passed,
        then this value will describe (like a bool value) if any checks failed.
    """
    exit_code = override if override is not None else bool(Globals.OUTPUT)
    try:
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as env_file:
            env_file.write(f"checks-failed={exit_code}\n")
    except (KeyError, FileNotFoundError):  # pragma: no cover
        # not executed on a github CI runner; ignore this error when executed locally
        pass
    return exit_code


# setup a separate logger for using github log commands
log_commander = logging.getLogger("LOG COMMANDER")  # create a child of our logger obj
log_commander.setLevel(logging.DEBUG)  # be sure that log commands are output
console_handler = logging.StreamHandler()  # Create special stdout stream handler
console_handler.setFormatter(logging.Formatter("%(message)s"))  # no formatted log cmds
log_commander.addHandler(console_handler)  # Use special handler for log_commander
log_commander.propagate = False


def start_log_group(name: str) -> None:
    """Begin a collapsable group of log statements.

    :param name: The name of the collapsable group
    """
    log_commander.fatal("::group::%s", name)


def end_log_group() -> None:
    """End a collapsable group of log statements."""
    log_commander.fatal("::endgroup::")


def is_file_in_list(paths: List[str], file_name: str, prompt: str) -> bool:
    """Determine if a file is specified in a list of paths and/or filenames.

    :param paths: A list of specified paths to compare with. This list can contain a
        specified file, but the file's path must be included as part of the
        filename.
    :param file_name: The file's path & name being sought in the ``paths`` list.
    :param prompt: A debugging prompt to use when the path is found in the list.

    :returns:

        - True if ``file_name`` is in the ``paths`` list.
        - False if ``file_name`` is not in the ``paths`` list.
    """
    for path in paths:
        result = os.path.commonpath(
            [PurePath(path).as_posix(), PurePath(file_name).as_posix()]
        )
        if result == path:
            logger.debug(
                '"./%s" is %s as specified in the domain "./%s"',
                file_name,
                prompt,
                path,
            )
            return True
    return False


def get_list_of_changed_files() -> None:
    """Fetch a list of the event's changed files. Sets the
    :attr:`~cpp_linter.Globals.FILES` attribute."""
    start_log_group("Get list of specified source files")
    if IS_ON_RUNNER:
        files_link = f"{GITHUB_API_URL}/repos/{GITHUB_REPOSITORY}/"
        if GITHUB_EVENT_NAME == "pull_request":
            files_link += f"pulls/{Globals.EVENT_PAYLOAD['number']}"
        else:
            if GITHUB_EVENT_NAME != "push":
                logger.warning(
                    "Triggered on unsupported event '%s'. Behaving like a push event.",
                    GITHUB_EVENT_NAME,
                )
            files_link += f"commits/{GITHUB_SHA}"
        logger.info("Fetching files list from url: %s", files_link)
        Globals.response_buffer = requests.get(
            files_link, headers=make_headers(use_diff=True)
        )
        log_response_msg()
        Globals.FILES = parse_diff(Globals.response_buffer.text)
    else:
        Globals.FILES = parse_diff(get_diff())


def filter_out_non_source_files(
    ext_list: List[str],
    ignored: List[str],
    not_ignored: List[str],
    lines_changed_only: int,
) -> bool:
    """Exclude undesired files (specified by user input :std:option:`--extensions`).
    This filtering is applied to the :attr:`~cpp_linter.Globals.FILES` attribute.

    :param ext_list: A list of file extensions that are to be examined.
    :param ignored: A list of paths to explicitly ignore.
    :param not_ignored: A list of paths to explicitly not ignore.
    :param lines_changed_only: A flag used for additional filtering based on what lines
        are changed in the file(s).

    :returns:
        True if there are files to check. False will invoke a early exit (in
        `main()`) when no files to be checked.
    """
    files = []
    for file in Globals.FILES:
        if (  # pylint: disable=too-many-boolean-expressions
            PurePath(file["filename"]).suffix.lstrip(".") in ext_list
            and (
                not is_file_in_list(ignored, file["filename"], "ignored")
                or is_file_in_list(not_ignored, file["filename"], "not ignored")
            )
            and (
                (lines_changed_only == 1 and file["line_filter"]["diff_chunks"])
                or (lines_changed_only == 2 and file["line_filter"]["lines_added"])
                or not lines_changed_only
            )
        ):
            files.append(file)

    if not files:
        logger.info("No source files need checking!")
        return False
    logger.info(
        "Giving attention to the following files:\n\t%s",
        "\n\t".join([f["filename"] for f in files]),
    )
    Globals.FILES = files
    if not IS_ON_RUNNER:  # if not executed on a github runner
        # dump altered json of changed files
        CACHE_PATH.mkdir(exist_ok=True)
        CHANGED_FILES_JSON.write_text(
            json.dumps(Globals.FILES, indent=2),
            encoding="utf-8",
        )
    return True


def verify_files_are_present() -> None:
    """Download the files if not present.

    .. hint::
        This function assumes the working directory is the root of the invoking
        repository. If files are not found, then they are downloaded to the working
        directory. This is bad for files with the same name from different folders.
    """
    for file in Globals.FILES:
        file_name = Path(file["filename"])
        if not file_name.exists():
            logger.warning("Could not find %s! Did you checkout the repo?", file_name)
            raw_url = f"https://github.com/{GITHUB_REPOSITORY}/raw/{GITHUB_SHA}/"
            raw_url += urllib.parse.quote(file["filename"], safe="")
            logger.info("Downloading file from url: %s", raw_url)
            Globals.response_buffer = requests.get(raw_url)
            # retain the repo's original structure
            Path.mkdir(file_name.parent, parents=True, exist_ok=True)
            file_name.write_text(Globals.response_buffer.text, encoding="utf-8")


def list_source_files(
    ext_list: List[str], ignored_paths: List[str], not_ignored: List[str]
) -> bool:
    """Make a list of source files to be checked. The resulting list is stored in
    :attr:`~cpp_linter.Globals.FILES`.

    :param ext_list: A list of file extensions that should by attended.
    :param ignored_paths: A list of paths to explicitly ignore.
    :param not_ignored: A list of paths to explicitly not ignore.

    :returns:
        True if there are files to check. False will invoke a early exit (in
        `main()` when no files to be checked.
    """
    start_log_group("Get list of specified source files")

    root_path = Path(".")
    for ext in ext_list:
        for rel_path in root_path.rglob(f"*.{ext}"):
            for parent in rel_path.parts[:-1]:
                if parent.startswith("."):
                    break
            else:
                file_path = rel_path.as_posix()
                logger.debug('"./%s" is a source code file', file_path)
                if not is_file_in_list(
                    ignored_paths, file_path, "ignored"
                ) or is_file_in_list(not_ignored, file_path, "not ignored"):
                    Globals.FILES.append(dict(filename=file_path))

    if Globals.FILES:
        logger.info(
            "Giving attention to the following files:\n\t%s",
            "\n\t".join([f["filename"] for f in Globals.FILES]),
        )
    else:
        logger.info("No source files found.")  # this might need to be warning
        return False
    return True


def run_clang_tidy(
    filename: str,
    file_obj: Dict[str, Any],
    version: str,
    checks: str,
    lines_changed_only: int,
    database: str,
    repo_root: str,
    extra_args: List[str],
) -> None:
    """Run clang-tidy on a certain file.

    :param filename: The name of the local file to run clang-tidy on.
    :param file_obj: JSON info about the file.
    :param version: The version of clang-tidy to run.
    :param checks: The `str` of comma-separated regulate expressions that describe
        the desired clang-tidy checks to be enabled/configured.
    :param lines_changed_only: A flag that forces focus on only changes in the event's
        diff info.
    :param database: The path to the compilation database.
    :param repo_root: The path to the repository root folder.
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
    """
    CACHE_PATH.mkdir(exist_ok=True)
    if checks == "-*":  # if all checks are disabled, then clang-tidy is skipped
        # clear the clang-tidy output file and exit function
        CLANG_TIDY_STDOUT.write_bytes(b"")
        return
    filename = PurePath(filename).as_posix()
    cmds = [
        assemble_version_exec("clang-tidy", version),
        f"--export-fixes={str(CLANG_TIDY_YML)}",
    ]
    if checks:
        cmds.append(f"-checks={checks}")
    if database:
        cmds.append("-p")
        if not PurePath(database).is_absolute():
            database = str(Path(RUNNER_WORKSPACE, repo_root, database).resolve())
        cmds.append(database)
    line_ranges = dict(
        name=filename, lines=range_of_changed_lines(file_obj, lines_changed_only, True)
    )
    if line_ranges["lines"]:
        # logger.info("line_filter = %s", json.dumps([line_ranges]))
        cmds.append(f"--line-filter={json.dumps([line_ranges])}")
    if len(extra_args) == 1 and " " in extra_args[0]:
        extra_args = extra_args[0].split()
    for extra_arg in extra_args:
        cmds.append(f"--extra-arg={extra_arg}")
    cmds.append(filename)
    # clear yml file's content before running clang-tidy
    CLANG_TIDY_YML.write_bytes(b"")
    logger.info('Running "%s"', " ".join(cmds))
    results = subprocess.run(cmds, capture_output=True)
    CLANG_TIDY_STDOUT.write_bytes(results.stdout)
    logger.debug("Output from clang-tidy:\n%s", results.stdout.decode())
    if CLANG_TIDY_YML.stat().st_size:
        parse_tidy_suggestions_yml()  # get clang-tidy fixes from yml
    if results.stderr:
        logger.debug(
            "clang-tidy made the following summary:\n%s", results.stderr.decode()
        )


def run_clang_format(
    filename: str,
    file_obj: Dict[str, Any],
    version: str,
    style: str,
    lines_changed_only: int,
) -> None:
    """Run clang-format on a certain file

    :param filename: The name of the local file to run clang-format on.
    :param file_obj: JSON info about the file.
    :param version: The version of clang-format to run.
    :param style: The clang-format style rules to adhere. Set this to 'file' to
        use the relative-most .clang-format configuration file.
    :param lines_changed_only: A flag that forces focus on only changes in the event's
        diff info.
    """
    CACHE_PATH.mkdir(exist_ok=True)
    if not style:  # if `style` == ""
        CLANG_FORMAT_XML.write_bytes(b"")
        return  # clear any previous output and exit
    cmds = [
        assemble_version_exec("clang-format", version),
        f"-style={style}",
        "--output-replacements-xml",
    ]
    ranges = cast(
        List[List[int]],
        range_of_changed_lines(file_obj, lines_changed_only, get_ranges=True),
    )
    for span in ranges:
        cmds.append(f"--lines={span[0]}:{span[1]}")
    cmds.append(PurePath(filename).as_posix())
    logger.info('Running "%s"', " ".join(cmds))
    results = subprocess.run(cmds, capture_output=True)
    CLANG_FORMAT_XML.write_bytes(results.stdout)
    if results.returncode:
        logger.debug(
            "%s raised the following error(s):\n%s", cmds[0], results.stderr.decode()
        )


def create_comment_body(
    filename: str,
    file_obj: Dict[str, Any],
    lines_changed_only: int,
    tidy_notes: List[TidyNotification],
):
    """Create the content for a thread comment about a certain file.
    This is a helper function to `capture_clang_tools_output()`.

    :param filename: The file's name (& path).
    :param file_obj: The file's JSON `dict`.
    :param lines_changed_only: A flag used to filter the comment based on line changes.
    :param tidy_notes: A list of cached notifications from clang-tidy. This is used to
        avoid duplicated content in comment, and it is later used again by
        `make_annotations()` after `capture_clang_tools_output()` is finished.
    """
    ranges = range_of_changed_lines(file_obj, lines_changed_only)
    if CLANG_TIDY_STDOUT.exists() and CLANG_TIDY_STDOUT.stat().st_size:
        parse_tidy_output()  # get clang-tidy fixes from stdout
        comment_output = ""
        if Globals.PAYLOAD_TIDY:
            Globals.PAYLOAD_TIDY += "<hr></details>"
        for fix in GlobalParser.tidy_notes:
            if lines_changed_only and fix.line not in ranges:
                continue
            comment_output += repr(fix)
            tidy_notes.append(fix)
        if comment_output:
            Globals.PAYLOAD_TIDY += f"<details><summary>{filename}</summary><br>\n"
            Globals.PAYLOAD_TIDY += comment_output
        GlobalParser.tidy_notes.clear()  # empty list to avoid duplicated output

    if CLANG_FORMAT_XML.exists() and CLANG_FORMAT_XML.stat().st_size:
        parse_format_replacements_xml(PurePath(filename).as_posix())
        if GlobalParser.format_advice and GlobalParser.format_advice[-1].replaced_lines:
            should_comment = lines_changed_only == 0
            if not should_comment:
                for line in [
                    replacement.line
                    for replacement in GlobalParser.format_advice[-1].replaced_lines
                ]:
                    if line in ranges:
                        should_comment = True
                        break
            if should_comment:
                if not Globals.OUTPUT:
                    Globals.OUTPUT = "<!-- cpp linter action -->\n## :scroll: "
                    Globals.OUTPUT += "Run `clang-format` on the following files\n"
                Globals.OUTPUT += f"- [ ] {file_obj['filename']}\n"


def capture_clang_tools_output(
    version: str,
    checks: str,
    style: str,
    lines_changed_only: int,
    database: str,
    repo_root: str,
    extra_args: List[str],
):
    """Execute and capture all output from clang-tidy and clang-format. This aggregates
    results in the :attr:`~cpp_linter.Globals.OUTPUT`.

    :param version: The version of clang-tidy to run.
    :param checks: The `str` of comma-separated regulate expressions that describe
        the desired clang-tidy checks to be enabled/configured.
    :param style: The clang-format style rules to adhere. Set this to 'file' to
        use the relative-most .clang-format configuration file.
    :param lines_changed_only: A flag that forces focus on only changes in the event's
        diff info.
    :param database: The path to the compilation database.
    :param repo_root: The path to the repository root folder.
    :param extra_args: A list of extra arguments used by clang-tidy as compiler
        arguments.
    """
    # temporary cache of parsed notifications for use in log commands
    tidy_notes: List[TidyNotification] = []
    for file in Globals.FILES:
        filename = cast(str, file["filename"])
        start_log_group(f"Performing checkup on {filename}")
        run_clang_tidy(
            filename,
            file,
            version,
            checks,
            lines_changed_only,
            database,
            repo_root,
            extra_args,
        )
        run_clang_format(filename, file, version, style, lines_changed_only)
        end_log_group()

        create_comment_body(filename, file, lines_changed_only, tidy_notes)

    if Globals.PAYLOAD_TIDY:
        if not Globals.OUTPUT:
            Globals.OUTPUT = "<!-- cpp linter action -->\n"
        else:
            Globals.OUTPUT += "\n---\n"
        Globals.OUTPUT += "## :speech_balloon: Output from `clang-tidy`\n"
        Globals.OUTPUT += Globals.PAYLOAD_TIDY
    GlobalParser.tidy_notes = tidy_notes[:]  # restore cache of notifications


def post_push_comment(base_url: str, user_id: int) -> bool:
    """POST action's results for a push event.

    :param base_url: The root of the url used to interact with the REST API via
        `requests`.
    :param user_id: The user's account ID number.

    :returns:
        A bool describing if the linter checks passed. This is used as the action's
        output value (a soft exit code).
    """
    comments_url = base_url + f"commits/{GITHUB_SHA}/comments"
    remove_bot_comments(comments_url, user_id)

    if Globals.OUTPUT:  # diff comments are not supported for push events (yet)
        payload = json.dumps({"body": Globals.OUTPUT})
        logger.debug("payload body:\n%s", json.dumps({"body": Globals.OUTPUT}))
        Globals.response_buffer = requests.post(
            comments_url, headers=make_headers(), data=payload
        )
        logger.info(
            "Got %d response from POSTing comment", Globals.response_buffer.status_code
        )
        log_response_msg()
    return bool(Globals.OUTPUT)


def post_diff_comments(base_url: str, user_id: int) -> bool:
    """Post comments inside a unified diff (only PRs are supported).

    :param base_url: The root of the url used to interact with the REST API via
        `requests`.
    :param user_id: The user's account ID number.

    :returns:
        A bool describing if the linter checks passed. This is used as the action's
        output value (a soft exit code).
    """
    comments_url = base_url + "pulls/comments/"  # for use with comment_id
    payload = list_diff_comments(2)  # only focus on additions in diff
    logger.info("Posting %d comments", len(payload))

    # uncomment the next 3 lines for debug output without posting a comment
    # for i, comment in enumerate(payload):
    #     logger.debug("comments %d: %s", i, json.dumps(comment, indent=2))
    # return

    # get existing review comments
    reviews_url = base_url + f'pulls/{Globals.EVENT_PAYLOAD["number"]}/'
    Globals.response_buffer = requests.get(reviews_url + "comments")
    existing_comments = json.loads(Globals.response_buffer.text)
    # filter out comments not made by our bot
    for index, comment in enumerate(existing_comments):
        if not comment["body"].startswith("<!-- cpp linter action -->"):
            del existing_comments[index]

    # conditionally post comments in the diff
    for i, body in enumerate(payload):
        # check if comment is already there
        already_posted = False
        comment_id = None
        for comment in existing_comments:
            if (
                int(comment["user"]["id"]) == user_id
                and comment["line"] == body["line"]
                and comment["path"] == body["path"]
            ):
                already_posted = True
                if comment["body"] != body["body"]:
                    comment_id = str(comment["id"])  # use this to update comment
                else:
                    break
        if already_posted and comment_id is None:
            logger.info("comment %d already posted", i)
            continue  # don't bother re-posting the same comment

        # update ot create a review comment (in the diff)
        logger.debug("Payload %d body = %s", i, json.dumps(body))
        if comment_id is not None:
            Globals.response_buffer = requests.patch(
                comments_url + comment_id,
                headers=make_headers(),
                data=json.dumps({"body": body["body"]}),
            )
            logger.info(
                "Got %d from PATCHing comment %d (%d)",
                Globals.response_buffer.status_code,
                i,
                comment_id,
            )
            log_response_msg()
        else:
            Globals.response_buffer = requests.post(
                reviews_url + "comments", headers=make_headers(), data=json.dumps(body)
            )
            logger.info(
                "Got %d from POSTing review comment %d",
                Globals.response_buffer.status_code,
                i,
            )
            log_response_msg()
    return bool(payload)


def post_pr_comment(base_url: str, user_id: int) -> bool:
    """POST action's results for a push event.

    :param base_url: The root of the url used to interact with the REST API via
        `requests`.
    :param user_id: The user's account ID number.

    :returns:
        A bool describing if the linter checks passed. This is used as the action's
        output value (a soft exit code).
    """
    comments_url = base_url + f'issues/{Globals.EVENT_PAYLOAD["number"]}/comments'
    remove_bot_comments(comments_url, user_id)
    payload = ""
    if Globals.OUTPUT:
        payload = json.dumps({"body": Globals.OUTPUT})
        logger.debug(
            "payload body:\n%s", json.dumps({"body": Globals.OUTPUT}, indent=2)
        )
        Globals.response_buffer = requests.post(
            comments_url, headers=make_headers(), data=payload
        )
        logger.info("Got %d from POSTing comment", Globals.response_buffer.status_code)
        log_response_msg()
    return bool(payload)


def post_results(use_diff_comments: bool, user_id: int = 41898282):
    """Post action's results using REST API.

    :param use_diff_comments: This flag enables making/updating comments in the PR's
        diff info.
    :param user_id: The user's account ID number. Defaults to the generic bot's ID.
    """
    if not GITHUB_TOKEN:
        logger.error("The GITHUB_TOKEN is required!")
        sys.exit(set_exit_code(1))

    base_url = f"{GITHUB_API_URL}/repos/{GITHUB_REPOSITORY}/"
    checks_passed = True
    if GITHUB_EVENT_NAME == "pull_request":
        checks_passed = post_pr_comment(base_url, user_id)
        if use_diff_comments:
            checks_passed = post_diff_comments(base_url, user_id)
    elif GITHUB_EVENT_NAME == "push":
        checks_passed = post_push_comment(base_url, user_id)
    set_exit_code(1 if checks_passed else 0)


def make_annotations(
    style: str, file_annotations: bool, lines_changed_only: int
) -> bool:
    """Use github log commands to make annotations from clang-format and
    clang-tidy output.

    :param style: The chosen code style guidelines. The value 'file' is replaced with
        'custom style'.
    :param file_annotations: A flag that corresponds to the
        :std:option:`--file-annotations` CLI option.
    :param lines_changed_only: Corresponds to the :std:option:`--lines-changed-only` CLI
        option.

        - ``0`` means all lines.
        - ``1`` means only lines in the diff chunks.
        - ``2`` means only lines in the diff with additions.

    :returns:
        A boolean describing if any annotations were made.
    """
    count = 0
    files = (
        Globals.FILES
        if GITHUB_EVENT_NAME == "pull_request" or isinstance(Globals.FILES, list)
        else cast(Dict[str, Any], Globals.FILES)["files"]
    )
    for advice, file in zip(GlobalParser.format_advice, files):
        line_filter = cast(List[int], range_of_changed_lines(file, lines_changed_only))
        if advice.replaced_lines:
            if file_annotations:
                output = advice.log_command(style, line_filter)
                if output is not None:
                    log_commander.info(output)
                    count += 1
    for note in GlobalParser.tidy_notes:
        if lines_changed_only:
            filename = note.filename.replace("\\", "/")
            line_filter = []
            for file in files:
                if filename == file["filename"]:
                    line_filter = cast(
                        List[int], range_of_changed_lines(file, lines_changed_only)
                    )
                    break
            else:
                continue
            if note.line in line_filter or not line_filter:
                count += 1
                log_commander.info(note.log_command())
        else:
            count += 1
            log_commander.info(note.log_command())
    logger.info("Created %d annotations", count)
    return bool(count)


def parse_ignore_option(paths: str) -> Tuple[List[str], List[str]]:
    """Parse a given string of paths (separated by a ``|``) into ``ignored`` and
    ``not_ignored`` lists of strings.

    :param paths: This argument conforms to the input value of CLI arg
        :std:option:`--ignore`.

    :returns:
        Returns a tuple of lists in which each list is a set of strings.

        - index 0 is the ``ignored`` list
        - index 1 is the ``not_ignored`` list
    """
    ignored, not_ignored = ([], [])

    for path in paths.split("|"):
        is_included = path.startswith("!")
        if path.startswith("!./" if is_included else "./"):
            path = path.replace("./", "", 1)  # relative dir is assumed
        path = path.strip()  # strip leading/trailing spaces
        if is_included:
            not_ignored.append(path[1:])  # strip leading `!`
        else:
            ignored.append(path)

    # auto detect submodules
    gitmodules = Path(".gitmodules")
    if gitmodules.exists():
        submodules = configparser.ConfigParser()
        submodules.read(gitmodules.resolve().as_posix())
        for module in submodules.sections():
            path = submodules[module]["path"]
            if path not in not_ignored:
                logger.info("Appending submodule to ignored paths: %s", path)
                ignored.append(path)

    if ignored:
        logger.info(
            "Ignoring the following paths/files:\n\t./%s",
            "\n\t./".join(f for f in ignored),
        )
    if not_ignored:
        logger.info(
            "Not ignoring the following paths/files:\n\t./%s",
            "\n\t./".join(f for f in not_ignored),
        )
    return (ignored, not_ignored)


def main():
    """The main script."""

    # The parsed CLI args
    args = cli_arg_parser.parse_args()

    #  force files-changed-only to reflect value of lines-changed-only
    if args.lines_changed_only:
        args.files_changed_only = True

    # set logging verbosity
    logger.setLevel(int(args.verbosity))

    # prepare ignored paths list
    ignored, not_ignored = parse_ignore_option(args.ignore)

    logger.info("processing %s event", GITHUB_EVENT_NAME)

    # change working directory
    os.chdir(args.repo_root)

    if GITHUB_EVENT_PATH:
        # load event's json info about the workflow run
        Globals.EVENT_PAYLOAD = json.loads(
            Path(GITHUB_EVENT_PATH).read_text(encoding="utf-8")
        )
    if logger.getEffectiveLevel() <= logging.DEBUG:
        start_log_group("Event json from the runner")
        logger.debug(json.dumps(Globals.EVENT_PAYLOAD))
        end_log_group()

    exit_early = False
    if args.files_changed_only:
        get_list_of_changed_files()
        exit_early = not filter_out_non_source_files(
            args.extensions,
            ignored,
            not_ignored,
            args.lines_changed_only,
        )
        if not exit_early:
            verify_files_are_present()
    else:
        exit_early = not list_source_files(args.extensions, ignored, not_ignored)
    end_log_group()
    if exit_early:
        sys.exit(set_exit_code(0))

    capture_clang_tools_output(
        args.version,
        args.tidy_checks,
        args.style,
        args.lines_changed_only,
        args.database,
        args.repo_root,
        args.extra_arg,
    )

    start_log_group("Posting comment(s)")
    thread_comments_allowed = True
    if GITHUB_EVENT_PATH and "private" in Globals.EVENT_PAYLOAD["repository"]:
        thread_comments_allowed = (
            Globals.EVENT_PAYLOAD["repository"]["private"] is not True
        )
    if args.thread_comments and thread_comments_allowed:
        post_results(False)  # False is hard-coded to disable diff comments.
    set_exit_code(
        int(
            make_annotations(args.style, args.file_annotations, args.lines_changed_only)
        )
    )
    end_log_group()


if __name__ == "__main__":
    main()
