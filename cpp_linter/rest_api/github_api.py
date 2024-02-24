"""A module that holds any github-specific interactions. Most of this functionality is
designed around GitHub's REST API.

.. seealso::

    - `github rest API reference for pulls <https://docs.github.com/en/rest/pulls>`_
    - `github rest API reference for commits <https://docs.github.com/en/rest/commits>`_
    - `github rest API reference for repos <https://docs.github.com/en/rest/repos>`_
    - `github rest API reference for issues <https://docs.github.com/en/rest/issues>`_
"""
import json
import logging
from os import environ
from pathlib import Path
import urllib.parse
import sys
import time
from typing import Dict, List, Any, cast, Optional, Tuple, Union, Sequence

from pygit2 import Patch  # type: ignore
import requests
from ..common_fs import FileObj, CACHE_PATH
from ..clang_tools.clang_format import FormatAdvice, formalize_style_name
from ..clang_tools.clang_tidy import TidyAdvice
from ..loggers import start_log_group, logger, log_response_msg, log_commander
from ..git import parse_diff, get_diff
from . import RestApiClient, USER_OUTREACH, COMMENT_MARKER


class GithubApiClient(RestApiClient):
    def __init__(self) -> None:
        super().__init__()
        # create default headers to be used for all HTTP requests
        self.session.headers.update(self.make_headers())

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

        # The remain API requests allowed under the given token (if any).
        self._rate_limit_remaining = -1  # -1 means unknown
        # a counter for avoiding secondary rate limits
        self._rate_limit_back_step = 0

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

    @staticmethod
    def _rate_limit_exceeded(
        response_headers: Union[
            requests.structures.CaseInsensitiveDict, Dict[str, Any]
        ],
    ):
        logger.error("RATE LIMIT EXCEEDED!")
        if "x-ratelimit-reset" in response_headers:
            reset_epoch = time.gmtime(
                int(cast(str, response_headers.get("x-ratelimit-reset")))
            )
            logger.error(
                "Github REST API rate limit resets on %s",
                time.strftime("%d %B %Y %H:%M +0000", reset_epoch),
            )

    def api_request(
        self,
        url: str,
        method: Optional[str] = None,
        data: Optional[str] = None,
        headers: Optional[Dict[str, Any]] = None,
    ) -> Optional[requests.Response]:
        if self._rate_limit_back_step > 5 or self._rate_limit_remaining == 0:
            self._rate_limit_exceeded({})
            return None
        response = self.session.request(
            method=method or ("GET" if data is None else "POST"),
            url=url,
            headers=headers,
            data=data,
        )
        self._rate_limit_remaining = int(
            response.headers.get("x-ratelimit-remaining", "-1")
        )
        log_response_msg(response)
        if response.status_code >= 400:
            if response.status_code in [403, 429]:  # rate limit exceeded
                # secondary rate limit handling
                if "retry-after" in response.headers:
                    wait_time = (
                        float(cast(str, response.headers.get("retry-after")))
                        * self._rate_limit_back_step
                    )
                    logger.warning(
                        "SECONDARY RATE LIMIT HIT! Backing off for %f seconds",
                        wait_time,
                    )
                    time.sleep(wait_time)
                    self._rate_limit_back_step += 1
                    return self.api_request(
                        url, method=method, data=data, headers=headers
                    )
                # primary rate limit handling
                if self._rate_limit_remaining == 0:
                    self._rate_limit_exceeded(response.headers)
            return None
        self._rate_limit_back_step = 0
        return response

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
            response_buffer = self.api_request(
                url=files_link, headers=self.make_headers(use_diff=True)
            )
            files = (
                []
                if response_buffer is None
                else parse_diff(
                    response_buffer.text,
                    extensions,
                    ignored,
                    not_ignored,
                    lines_changed_only,
                )
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
                response_buffer = self.api_request(url=raw_url)
                # retain the repo's original structure
                Path.mkdir(file_name.parent, parents=True, exist_ok=True)
                file_name.write_text(
                    "" if response_buffer is None else response_buffer.text,
                    encoding="utf-8",
                )

    def make_headers(self, use_diff: bool = False) -> Dict[str, str]:
        headers = {
            "Accept": "application/vnd.github." + ("diff" if use_diff else "raw+json"),
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
        if thread_comments != "false":
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

        if self.event_name == "pull_request" and (tidy_review or format_review):
            self.post_review(
                files, tidy_advice, format_advice, tidy_review, format_review, no_lgtm
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
        count = -1
        if self.event_name == "pull_request":
            comments_url = base_url + f'issues/{self.event_payload["number"]}'
            response_buffer = self.api_request(comments_url)
            if response_buffer is not None:
                count = cast(int, response_buffer.json()["comments"])
        else:
            comments_url = base_url + f"commits/{self.sha}"
            response_buffer = self.api_request(comments_url)
            if response_buffer is not None:
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
                req_meth = "PATCH"
            else:
                req_meth = "POST"
            payload = json.dumps({"body": comment})
            logger.debug("payload body:\n%s", payload)
            response_buffer = self.api_request(
                comments_url, method=req_meth, data=payload
            )
            if response_buffer is not None:
                logger.info(
                    "Got %d response from %sing comment",
                    response_buffer.status_code,
                    "POST" if comment_url is None else "PATCH",
                )

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
            response_buffer = self.api_request(comments_url + f"?page={page}")
            if response_buffer is None:
                return comment_url  # error getting comments for the thread; stop here
            comments = cast(List[Dict[str, Any]], response_buffer.json())
            if logger.level >= logging.DEBUG:
                json_comments = Path(f"{CACHE_PATH}/comments-pg{page}.json")
                json_comments.write_text(
                    json.dumps(comments, indent=2), encoding="utf-8"
                )

            page += 1
            count -= len(comments)
            for comment in comments:
                # only search for comments that begin with a specific html comment.
                # the specific html comment is our action's name
                if cast(str, comment["body"]).startswith(COMMENT_MARKER):
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
                        response_buffer = self.api_request(url, method="DELETE")
                        if response_buffer is not None:
                            logger.info(
                                "Got %d from DELETE %s",
                                response_buffer.status_code,
                                url[url.find(".com") + 4 :],
                            )
                    if not delete:
                        comment_url = cast(str, comment["url"])
        return comment_url

    def post_review(
        self,
        files: List[FileObj],
        tidy_advice: List[TidyAdvice],
        format_advice: List[FormatAdvice],
        tidy_review: bool,
        format_review: bool,
        no_lgtm: bool,
    ):
        url = f"{self.api_url}/repos/{self.repo}/pulls/{self.event_payload['number']}"
        response_buffer = self.api_request(url)
        url += "/reviews"
        is_draft = True
        if response_buffer is not None:
            pr_payload = response_buffer.json()
            is_draft = cast(Dict[str, bool], pr_payload).get("draft", False)
            is_open = cast(Dict[str, str], pr_payload).get("state", "open") == "open"
        if "GITHUB_TOKEN" not in environ:
            logger.error("A GITHUB_TOKEN env var is required to post review comments")
            sys.exit(self.set_exit_code(1))
        self._dismiss_stale_reviews(url)
        if is_draft or not is_open:  # is PR open and ready for review
            return  # don't post reviews
        body = f"{COMMENT_MARKER}## Cpp-linter Review\n"
        payload_comments = []
        total_changes = 0
        summary_only = (
            environ.get("CPP_LINTER_PR_REVIEW_SUMMARY_ONLY", "false") == "true"
        )
        advice: Dict[str, Sequence[Union[TidyAdvice, FormatAdvice]]] = {}
        if format_review:
            advice["clang-format"] = format_advice
        if tidy_review:
            advice["clang-tidy"] = tidy_advice
        for tool_name, tool_advice in advice.items():
            comments, total, patch = self.create_review_comments(
                files, tool_advice, summary_only
            )
            total_changes += total
            if not summary_only:
                payload_comments.extend(comments)
                if total and total != len(comments):
                    body += f"Only {len(comments)} out of {total} {tool_name} "
                    body += "concerns fit within this pull request's diff.\n"
            if patch:
                body += f"\n<details><summary>Click here for the full {tool_name} patch"
                body += f"</summary>\n\n\n```diff\n{patch}\n```\n\n\n</details>\n\n"
            elif not total:
                body += f"No concerns from {tool_name}.\n"
        if total_changes:
            event = "REQUEST_CHANGES"
        else:
            if no_lgtm:
                logger.debug("Not posting an approved review because `no-lgtm` is true")
                return
            body += "\nGreat job! :tada:"
            event = "APPROVE"
        body += USER_OUTREACH
        payload = {
            "body": body,
            "event": event,
            "comments": payload_comments,
        }
        response_buffer = self.api_request(url, data=json.dumps(payload))

    @staticmethod
    def create_review_comments(
        files: List[FileObj],
        tool_advice: Sequence[Union[FormatAdvice, TidyAdvice]],
        summary_only: bool,
    ) -> Tuple[List[Dict[str, Any]], int, str]:
        """Creates a batch of comments for a specific clang tool's PR review"""
        total = 0
        comments = []
        full_patch = ""
        for file, advice in zip(files, tool_advice):
            assert advice.patched, f"No suggested patch found for {file.name}"
            patch = Patch.create_from(
                old=Path(file.name).read_bytes(),
                new=advice.patched,
                old_as_path=file.name,
                new_as_path=file.name,
                context_lines=0,  # trim all unchanged lines from start/end of hunks
            )
            full_patch += patch.text
            for hunk in patch.hunks:
                total += 1
                if summary_only:
                    continue
                new_hunk_range = file.is_hunk_contained(hunk)
                if new_hunk_range is None:
                    continue
                start_lines, end_lines = new_hunk_range
                comment: Dict[str, Any] = {"path": file.name}
                body = ""
                if isinstance(advice, TidyAdvice):
                    body += "### clang-tidy "
                    diagnostics = advice.diagnostics_in_range(start_lines, end_lines)
                    if diagnostics:
                        body += "diagnostics\n" + diagnostics
                    else:
                        body += "suggestions\n"
                else:
                    body += "### clang-format suggestions\n"
                if start_lines < end_lines:
                    comment["start_line"] = start_lines
                comment["line"] = end_lines
                suggestion = ""
                removed = []
                for line in hunk.lines:
                    if line.origin in ["+", " "]:
                        suggestion += line.content
                    else:
                        removed.append(line.old_lineno)
                if not suggestion and removed:
                    body += "\nPlease remove the line(s)\n- "
                    body += "\n- ".join([str(x) for x in removed])
                else:
                    body += f"\n```suggestion\n{suggestion}```"
                comment["body"] = body
                comments.append(comment)

        if tool_advice and isinstance(tool_advice[0], TidyAdvice):
            # now check for clang-tidy warnings with no fixes applied
            for file, tidy_advice in zip(files, tool_advice):
                assert isinstance(tidy_advice, TidyAdvice)
                for note in tidy_advice.notes:
                    if not note.applied_fixes:  # if no fix was applied
                        total += 1
                        line_numb = int(note.line)
                        if file.is_range_contained(start=line_numb, end=line_numb + 1):
                            diag: Dict[str, Any] = {
                                "path": file.name,
                                "line": note.line,
                            }
                            body = f"### clang-tidy diagnostic\n**{file.name}:"
                            body += f"{note.line}:{note.cols}:** {note.severity}: "
                            body += f"[{note.diagnostic_link}]\n> {note.rationale}\n"
                            if note.fixit_lines:
                                body += f'```{Path(file.name).suffix.lstrip(".")}\n'
                                for line in note.fixit_lines:
                                    body += f"{line}\n"
                                body += "```\n"
                            diag["body"] = body
                            comments.append(diag)
        return (comments, total, full_patch)

    def _dismiss_stale_reviews(self, url: str):
        """Dismiss all reviews that were previously created by cpp-linter"""
        response_buffer = self.api_request(url)
        if response_buffer is None:
            logger.error("Failed to poll existing reviews for dismissal")
        else:
            reviews: List[Dict[str, Any]] = response_buffer.json()
            for review in reviews:
                if (
                    "body" in review
                    and cast(str, review["body"]).startswith(COMMENT_MARKER)
                    and "state" in review
                    and review["state"] not in ["PENDING", "DISMISSED"]
                ):
                    assert "id" in review
                    response_buffer = self.api_request(
                        f"{url}/{review['id']}/dismissals",
                        method="PUT",
                        data=json.dumps(
                            {"message": "outdated suggestion", "event": "DISMISS"}
                        ),
                    )
