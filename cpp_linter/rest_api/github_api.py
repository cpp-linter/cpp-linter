"""A module that holds any github-specific interactions. Most of this functionality is
designed around GitHub's REST API.

.. seealso::

    - `github rest API reference for pulls <https://docs.github.com/en/rest/pulls>`_
    - `github rest API reference for commits <https://docs.github.com/en/rest/commits>`_
    - `github rest API reference for repos <https://docs.github.com/en/rest/repos>`_
    - `github rest API reference for issues <https://docs.github.com/en/rest/issues>`_
"""
import json
from os import environ
from pathlib import Path
import urllib.parse
import sys
from typing import Dict, List, Any, cast, Optional, Tuple

from ..common_fs import FileObj, CACHE_PATH
from ..clang_tools.clang_format import FormatAdvice, formalize_style_name
from ..clang_tools.clang_tidy import TidyAdvice
from ..loggers import start_log_group, logger, log_response_msg, log_commander
from ..git import parse_diff, get_diff
from . import RestApiClient


class GithubApiClient(RestApiClient):
    def __init__(self) -> None:
        super().__init__()
        #: The base domain for the REST API
        self.api_url = environ.get("GITHUB_API_URL", "https://api.github.com")
        #: The ``owner``/``repository`` name.
        self.repo = environ.get("GITHUB_REPOSITORY", "")
        #: The triggering event type's name
        self.event_name = environ.get("GITHUB_EVENT_NAME", "unknown")
        #: The HEAD commit's SHA
        self.sha = environ.get("GITHUB_SHA", "")
        #: A flag that describes if debug logs are enabled.
        self.debug_enabled = environ.get("ACTIONS_STEP_DEBUG", "") == "true"

        #: The event payload delivered as the web hook for the workflow run.
        self.event_payload: Dict[str, Any] = {}
        event_path = environ.get("GITHUB_EVENT_PATH", "")
        if event_path:
            self.event_payload = json.loads(
                Path(event_path).read_text(encoding="utf-8")
            )

    def set_exit_code(
        self,
        checks_failed: int,
        format_checks_failed: Optional[int] = None,
        tidy_checks_failed: Optional[int] = None,
    ):
        try:
            with open(environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as env_file:
                env_file.write(f"checks-failed={checks_failed}\n")
                env_file.write(
                    f"clang-format-checks-failed={format_checks_failed or 0}\n"
                )
                env_file.write(f"clang-tidy-checks-failed={tidy_checks_failed or 0}\n")
        except (KeyError, FileNotFoundError):  # pragma: no cover
            # not executed on a github CI runner.
            pass  # ignore this error when executed locally
        return super().set_exit_code(
            checks_failed, format_checks_failed, tidy_checks_failed
        )

    def get_list_of_changed_files(
        self,
        extensions: List[str],
        ignored: List[str],
        not_ignored: List[str],
        lines_changed_only: int,
    ) -> List[FileObj]:
        start_log_group("Get list of specified source files")
        if environ.get("CI", "false") == "true":
            files_link = f"{self.api_url}/repos/{self.repo}/"
            if self.event_name == "pull_request":
                files_link += f"pulls/{self.event_payload['number']}"
            else:
                if self.event_name != "push":
                    logger.warning(
                        "Triggered on unsupported event '%s'. Behaving like a push "
                        "event.",
                        self.event_name,
                    )
                files_link += f"commits/{self.sha}"
            logger.info("Fetching files list from url: %s", files_link)
            response_buffer = self.session.get(
                files_link, headers=self.make_headers(use_diff=True)
            )
            log_response_msg(response_buffer)
            files = parse_diff(
                response_buffer.text,
                extensions,
                ignored,
                not_ignored,
                lines_changed_only,
            )
        else:
            files = parse_diff(
                get_diff(), extensions, ignored, not_ignored, lines_changed_only
            )
        return files

    def verify_files_are_present(self, files: List[FileObj]) -> None:
        """Download the files if not present.

        :param files: A list of files to check for existence.

        .. hint::
            This function assumes the working directory is the root of the invoking
            repository. If files are not found, then they are downloaded to the working
            directory. This is bad for files with the same name from different folders.
        """
        for file in files:
            file_name = Path(file.name)
            if not file_name.exists():
                logger.warning(
                    "Could not find %s! Did you checkout the repo?", file_name
                )
                raw_url = f"https://github.com/{self.repo}/raw/{self.sha}/"
                raw_url += urllib.parse.quote(file.name, safe="")
                logger.info("Downloading file from url: %s", raw_url)
                response_buffer = self.session.get(raw_url)
                # retain the repo's original structure
                Path.mkdir(file_name.parent, parents=True, exist_ok=True)
                file_name.write_text(response_buffer.text, encoding="utf-8")

    def make_headers(self, use_diff: bool = False) -> Dict[str, str]:
        headers = {
            "Accept": "application/vnd.github." + ("diff" if use_diff else "text+json"),
        }
        gh_token = environ.get("GITHUB_TOKEN", "")
        if gh_token:
            headers["Authorization"] = f"token {gh_token}"
        return headers

    def post_feedback(
        self,
        files: List[FileObj],
        format_advice: List[FormatAdvice],
        tidy_advice: List[TidyAdvice],
        thread_comments: str,
        no_lgtm: bool,
        step_summary: bool,
        file_annotations: bool,
        style: str,
        tidy_review: bool,
        format_review: bool,
    ):
        (comment, format_checks_failed, tidy_checks_failed) = super().make_comment(
            files, format_advice, tidy_advice
        )
        checks_failed = format_checks_failed + tidy_checks_failed
        thread_comments_allowed = True
        if self.event_payload and "private" in self.event_payload["repository"]:
            thread_comments_allowed = (
                self.event_payload["repository"]["private"] is not True
            )
        if thread_comments != "false" and thread_comments_allowed:
            if "GITHUB_TOKEN" not in environ:
                logger.error("The GITHUB_TOKEN is required!")
                sys.exit(self.set_exit_code(1))

            update_only = thread_comments == "update"
            is_lgtm = not checks_failed
            base_url = f"{self.api_url}/repos/{self.repo}/"
            count, comments_url = self._get_comment_count(base_url)
            if count >= 0:
                self.update_comment(
                    comment, comments_url, count, no_lgtm, update_only, is_lgtm
                )

        if file_annotations:
            self.make_annotations(files, format_advice, tidy_advice, style)

        if step_summary and "GITHUB_STEP_SUMMARY" in environ:
            with open(environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
                summary.write(f"\n{comment}\n")
        self.set_exit_code(checks_failed, format_checks_failed, tidy_checks_failed)

    def _get_comment_count(self, base_url: str) -> Tuple[int, str]:
        """Gets the comment count for the current event. Returns a negative count if
        failed. Also returns the comments_url for the current event."""
        headers = self.make_headers()
        count = -1
        if self.event_name == "pull_request":
            comments_url = base_url + f'issues/{self.event_payload["number"]}'
            response_buffer = self.session.get(comments_url, headers=headers)
            log_response_msg(response_buffer)
            if response_buffer.status_code == 200:
                count = cast(int, response_buffer.json()["comments"])
        else:
            comments_url = base_url + f"commits/{self.sha}"
            response_buffer = self.session.get(comments_url, headers=headers)
            log_response_msg(response_buffer)
            if response_buffer.status_code == 200:
                count = cast(int, response_buffer.json()["commit"]["comment_count"])
        return count, comments_url + "/comments"

    def make_annotations(
        self,
        files: List[FileObj],
        format_advice: List[FormatAdvice],
        tidy_advice: List[TidyAdvice],
        style: str,
    ) -> None:
        """Use github log commands to make annotations from clang-format and
        clang-tidy output.

        :param files: A list of objects, each describing a file's information.
        :param format_advice: A list of clang-format advice parallel to the list of
            ``files``.
        :param tidy_advice: A list of clang-tidy advice parallel to the list of
            ``files``.
        :param style: The chosen code style guidelines. The value 'file' is replaced
            with 'custom style'.
        """
        style_guide = formalize_style_name(style)
        for advice, file in zip(format_advice, files):
            if advice.replaced_lines:
                line_list = []
                for fix in advice.replaced_lines:
                    line_list.append(str(fix.line))
                output = "::notice file="
                name = file.name
                output += f"{name},title=Run clang-format on {name}::File {name}"
                output += f" does not conform to {style_guide} style guidelines. "
                output += "(lines {lines})".format(lines=", ".join(line_list))
                log_commander.info(output)
        for concerns, file in zip(tidy_advice, files):
            for note in concerns.notes:
                if note.filename == file.name:
                    output = "::{} ".format(
                        "notice" if note.severity.startswith("note") else note.severity
                    )
                    output += "file={file},line={line},title={file}:{line}:".format(
                        file=file.name, line=note.line
                    )
                    output += "{cols} [{diag}]::{info}".format(
                        cols=note.cols,
                        diag=note.diagnostic,
                        info=note.rationale,
                    )
                    log_commander.info(output)

    def update_comment(
        self,
        comment: str,
        comments_url: str,
        count: int,
        no_lgtm: bool,
        update_only: bool,
        is_lgtm: bool,
    ):
        """Updates the comment for an existing comment or posts a new comment if
        ``update_only`` is `False`.


        :param comment: The Comment to post.
        :param comments_url: The URL used to fetch the comments.
        :param count: The number of comments to traverse.
        :param no_lgtm: A flag to control if a "Looks Good To Me" comment should be
            posted. If this is `False`, then an outdated bot comment will still be
            deleted.
        :param update_only: A flag that describes if the outdated bot comment should
            only be updated (instead of replaced).
        :param is_lgtm: A flag the describes if the comment being posted is essentially
            a "Looks Good To Me" comment.
        """
        comment_url = self.remove_bot_comments(
            comments_url, count, delete=not update_only or (is_lgtm and no_lgtm)
        )
        if (is_lgtm and not no_lgtm) or not is_lgtm:
            if comment_url is not None:
                comments_url = comment_url
                req_meth = self.session.patch
            else:
                req_meth = self.session.post
            payload = json.dumps({"body": comment})
            logger.debug("payload body:\n%s", payload)
            response_buffer = req_meth(
                comments_url, headers=self.make_headers(), data=payload
            )
            logger.info(
                "Got %d response from %sing comment",
                response_buffer.status_code,
                "POST" if comment_url is None else "PATCH",
            )
            log_response_msg(response_buffer)

    def remove_bot_comments(
        self, comments_url: str, count: int, delete: bool
    ) -> Optional[str]:
        """Traverse the list of comments made by a specific user
        and remove all.

        :param comments_url: The URL used to fetch the comments.
        :param count: The number of comments to traverse.
        :param delete: A flag describing if first applicable bot comment should be
            deleted or not.

        :returns: If updating a comment, this will return the comment URL.
        """
        logger.info("comments_url: %s", comments_url)
        page = 1
        comment_url: Optional[str] = None
        while count:
            response_buffer = self.session.get(comments_url + f"?page={page}")
            if not log_response_msg(response_buffer):
                return comment_url  # error getting comments for the thread; stop here
            comments = cast(List[Dict[str, Any]], response_buffer.json())
            json_comments = Path(f"{CACHE_PATH}/comments-pg{page}.json")
            json_comments.write_text(json.dumps(comments, indent=2), encoding="utf-8")

            page += 1
            count -= len(comments)
            for comment in comments:
                # only search for comments that begin with a specific html comment.
                # the specific html comment is our action's name
                if cast(str, comment["body"]).startswith("<!-- cpp linter action -->"):
                    logger.debug(
                        "comment id %d from user %s (%d)",
                        comment["id"],
                        comment["user"]["login"],
                        comment["user"]["id"],
                    )
                    if delete or (not delete and comment_url is not None):
                        # if not updating: remove all outdated comments
                        # if updating: remove all outdated comments except the last one

                        # use saved comment_url if not None else current comment url
                        url = comment_url or comment["url"]
                        response_buffer = self.session.delete(
                            url, headers=self.make_headers()
                        )
                        logger.info(
                            "Got %d from DELETE %s",
                            response_buffer.status_code,
                            url[url.find(".com") + 4 :],
                        )
                        log_response_msg(response_buffer)
                    if not delete:
                        comment_url = cast(str, comment["url"])
        return comment_url
