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
from typing import Dict, List, Any, cast, Optional

from ..common_fs import FileObj, CACHE_PATH
from ..common_fs.file_filter import FileFilter
from ..clang_tools.clang_format import (
    formalize_style_name,
    tally_format_advice,
)
from ..clang_tools.clang_tidy import tally_tidy_advice
from ..clang_tools.patcher import ReviewComments, PatchMixin
from ..cli import Args
from ..loggers import logger, log_commander
from ..git import parse_diff, get_diff
from . import RestApiClient, USER_OUTREACH, COMMENT_MARKER, RateLimitHeaders

RATE_LIMIT_HEADERS = RateLimitHeaders(
    reset="x-ratelimit-reset",
    remaining="x-ratelimit-remaining",
    retry="retry-after",
)


class GithubApiClient(RestApiClient):
    """A class that describes the API used to interact with Github's REST API."""

    def __init__(self) -> None:
        super().__init__(rate_limit_headers=RATE_LIMIT_HEADERS)
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

        #: The pull request number for the event (if applicable).
        self.pull_request = -1
        event_path = environ.get("GITHUB_EVENT_PATH", "")
        if event_path:
            event_payload: Dict[str, Any] = json.loads(
                Path(event_path).read_text(encoding="utf-8")
            )
            self.pull_request = cast(int, event_payload.get("number", -1))

    def set_exit_code(
        self,
        checks_failed: int,
        format_checks_failed: Optional[int] = None,
        tidy_checks_failed: Optional[int] = None,
    ):
        if "GITHUB_OUTPUT" in environ:
            with open(environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as env_file:
                env_file.write(f"checks-failed={checks_failed}\n")
                env_file.write(
                    f"clang-format-checks-failed={format_checks_failed or 0}\n"
                )
                env_file.write(f"clang-tidy-checks-failed={tidy_checks_failed or 0}\n")
        return super().set_exit_code(
            checks_failed, format_checks_failed, tidy_checks_failed
        )

    def get_list_of_changed_files(
        self,
        file_filter: FileFilter,
        lines_changed_only: int,
    ) -> List[FileObj]:
        if environ.get("CI", "false") == "true":
            files_link = f"{self.api_url}/repos/{self.repo}/"
            if self.event_name == "pull_request":
                files_link += f"pulls/{self.pull_request}"
            else:
                if self.event_name != "push":
                    logger.warning(
                        "Triggered on unsupported event '%s'. Behaving like a push "
                        "event.",
                        self.event_name,
                    )
                files_link += f"commits/{self.sha}"
            logger.info("Fetching files list from url: %s", files_link)
            response = self.api_request(
                url=files_link, headers=self.make_headers(use_diff=True), strict=False
            )
            if response.status_code != 200:
                return self._get_changed_files_paginated(
                    files_link, lines_changed_only, file_filter
                )
            return parse_diff(response.text, file_filter, lines_changed_only)
        return parse_diff(get_diff(), file_filter, lines_changed_only)

    def _get_changed_files_paginated(
        self, url: Optional[str], lines_changed_only: int, file_filter: FileFilter
    ) -> List[FileObj]:
        """A fallback implementation of getting file changes using a paginated
        REST API endpoint."""
        logger.info(
            "Could not get raw diff of the %s event. "
            "Perhaps there are too many changes?",
            self.event_name,
        )
        assert url is not None
        if self.event_name == "pull_request":
            url += "/files"
        files = []
        while url is not None:
            response = self.api_request(url)
            url = RestApiClient.has_more_pages(response)
            file_list: List[Dict[str, Any]]
            if self.event_name == "pull_request":
                file_list = response.json()
            else:
                file_list = response.json()["files"]
            for file in file_list:
                assert "filename" in file
                file_name = file["filename"]
                if not file_filter.is_source_or_ignored(file_name):
                    continue
                old_name = file_name
                if "previous_filename" in file:
                    old_name = file["previous_filename"]
                assert "patch" in file
                file_diff = (
                    f"diff --git a/{old_name} b/{file_name}\n"
                    + f"--- a/{old_name}\n+++ b/{file_name}\n"
                    + file["patch"]
                )
                files.extend(parse_diff(file_diff, file_filter, lines_changed_only))
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
                raw_url = f"{self.api_url}/repos/{self.repo}/contents/"
                raw_url += urllib.parse.quote(file.name, safe="")
                raw_url += f"?ref={self.sha}"
                logger.info("Downloading file from url: %s", raw_url)
                response = self.api_request(url=raw_url)
                # retain the repo's original structure
                Path.mkdir(file_name.parent, parents=True, exist_ok=True)
                file_name.write_bytes(response.content)

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
        args: Args,
    ):
        format_checks_failed = tally_format_advice(files)
        tidy_checks_failed = tally_tidy_advice(files)
        checks_failed = format_checks_failed + tidy_checks_failed
        comment: Optional[str] = None

        if args.step_summary and "GITHUB_STEP_SUMMARY" in environ:
            comment = super().make_comment(
                files=files,
                format_checks_failed=format_checks_failed,
                tidy_checks_failed=tidy_checks_failed,
                len_limit=None,
            )
            with open(environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
                summary.write(f"\n{comment}\n")

        if args.file_annotations:
            self.make_annotations(
                files=files,
                style=args.style,
            )

        self.set_exit_code(
            checks_failed=checks_failed,
            format_checks_failed=format_checks_failed,
            tidy_checks_failed=tidy_checks_failed,
        )

        if args.thread_comments != "false":
            if "GITHUB_TOKEN" not in environ:
                logger.error("The GITHUB_TOKEN is required!")
                sys.exit(1)

            if comment is None or len(comment) >= 65535:
                comment = super().make_comment(
                    files=files,
                    format_checks_failed=format_checks_failed,
                    tidy_checks_failed=tidy_checks_failed,
                    len_limit=65535,
                )

            update_only = args.thread_comments == "update"
            is_lgtm = not checks_failed
            comments_url = f"{self.api_url}/repos/{self.repo}/"
            if self.event_name == "pull_request":
                comments_url += f"issues/{self.pull_request}"
            else:
                comments_url += f"commits/{self.sha}"
            comments_url += "/comments"
            self.update_comment(
                comment=comment,
                comments_url=comments_url,
                no_lgtm=args.no_lgtm,
                update_only=update_only,
                is_lgtm=is_lgtm,
            )

        if self.event_name == "pull_request" and (
            args.tidy_review or args.format_review
        ):
            self.post_review(
                files=files,
                tidy_review=args.tidy_review,
                format_review=args.format_review,
                no_lgtm=args.no_lgtm,
                passive_reviews=args.passive_reviews,
            )

    def make_annotations(
        self,
        files: List[FileObj],
        style: str,
    ) -> None:
        """Use github log commands to make annotations from clang-format and
        clang-tidy output.

        :param files: A list of objects, each describing a file's information.
        :param style: The chosen code style guidelines. The value 'file' is replaced
            with 'custom style'.
        """
        style_guide = formalize_style_name(style)
        for file_obj in files:
            if not file_obj.format_advice:
                continue
            if file_obj.format_advice.replaced_lines:
                line_list = []
                for fix in file_obj.format_advice.replaced_lines:
                    line_list.append(str(fix.line))
                output = "::notice file="
                name = file_obj.name
                output += f"{name},title=Run clang-format on {name}::File {name}"
                output += f" does not conform to {style_guide} style guidelines. "
                output += "(lines {lines})".format(lines=", ".join(line_list))
                log_commander.info(output)
        for file_obj in files:
            if not file_obj.tidy_advice:
                continue
            for note in file_obj.tidy_advice.notes:
                if note.filename == file_obj.name:
                    output = "::{} ".format(
                        "notice" if note.severity.startswith("note") else note.severity
                    )
                    output += "file={file},line={line},title={file}:{line}:".format(
                        file=file_obj.name, line=note.line
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
        no_lgtm: bool,
        update_only: bool,
        is_lgtm: bool,
    ):
        """Updates the comment for an existing comment or posts a new comment if
        ``update_only`` is `False`.


        :param comment: The Comment to post.
        :param comments_url: The URL used to fetch the comments.
        :param no_lgtm: A flag to control if a "Looks Good To Me" comment should be
            posted. If this is `True`, then an outdated bot comment will still be
            deleted.
        :param update_only: A flag that describes if the outdated bot comment should
            only be updated (instead of replaced).
        :param is_lgtm: A flag the describes if the comment being posted is essentially
            a "Looks Good To Me" comment.
        """
        comment_url = self.remove_bot_comments(
            comments_url, delete=not update_only or (is_lgtm and no_lgtm)
        )
        if (is_lgtm and not no_lgtm) or not is_lgtm:
            if comment_url is not None:
                comments_url = comment_url
                req_meth = "PATCH"
            else:
                req_meth = "POST"
            payload = json.dumps({"body": comment})
            logger.debug("payload body:\n%s", payload)
            self.api_request(url=comments_url, method=req_meth, data=payload)

    def remove_bot_comments(self, comments_url: str, delete: bool) -> Optional[str]:
        """Traverse the list of comments made by a specific user
        and remove all.

        :param comments_url: The URL used to fetch the comments.
        :param delete: A flag describing if first applicable bot comment should be
            deleted or not.

        :returns: If updating a comment, this will return the comment URL.
        """
        logger.debug("comments_url: %s", comments_url)
        comment_url: Optional[str] = None
        page = 1
        next_page: Optional[str] = comments_url + f"?page={page}&per_page=100"
        while next_page:
            response = self.api_request(url=next_page)
            next_page = self.has_more_pages(response)
            page += 1

            comments = cast(List[Dict[str, Any]], response.json())
            if logger.level >= logging.DEBUG:
                json_comments = Path(f"{CACHE_PATH}/comments-pg{page}.json")
                json_comments.write_text(
                    json.dumps(comments, indent=2), encoding="utf-8"
                )

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
                        self.api_request(url=url, method="DELETE", strict=False)
                    if not delete:
                        comment_url = cast(str, comment["url"])
        return comment_url

    def post_review(
        self,
        files: List[FileObj],
        tidy_review: bool,
        format_review: bool,
        no_lgtm: bool,
        passive_reviews: bool,
    ):
        url = f"{self.api_url}/repos/{self.repo}/pulls/{self.pull_request}"
        response = self.api_request(url=url)
        url += "/reviews"
        pr_info = response.json()
        is_draft = cast(Dict[str, bool], pr_info).get("draft", False)
        is_open = cast(Dict[str, str], pr_info).get("state", "open") == "open"
        if "GITHUB_TOKEN" not in environ:
            logger.error("A GITHUB_TOKEN env var is required to post review comments")
            sys.exit(1)
        self._dismiss_stale_reviews(url)
        if is_draft or not is_open:  # is PR open and ready for review
            return  # don't post reviews
        body = f"{COMMENT_MARKER}## Cpp-linter Review\n"
        payload_comments = []
        summary_only = environ.get(
            "CPP_LINTER_PR_REVIEW_SUMMARY_ONLY", "false"
        ).lower() in ("true", "on", "1")
        advice = []
        if format_review:
            advice.append("clang-format")
        if tidy_review:
            advice.append("clang-tidy")
        review_comments = ReviewComments()
        for tool_name in advice:
            self.create_review_comments(
                files=files,
                tidy_tool=tool_name == "clang-tidy",
                summary_only=summary_only,
                review_comments=review_comments,
            )
        (summary, comments) = review_comments.serialize_to_github_payload()
        if not summary_only:
            payload_comments.extend(comments)
        body += summary
        if sum(review_comments.tool_total.values()):
            event = "REQUEST_CHANGES"
        else:
            if no_lgtm:
                logger.debug("Not posting an approved review because `no-lgtm` is true")
                return
            body += "\nGreat job! :tada:"
            event = "APPROVE"
        if passive_reviews:
            event = "COMMENT"
        body += USER_OUTREACH
        payload = {
            "body": body,
            "event": event,
            "comments": payload_comments,
        }
        self.api_request(url=url, data=json.dumps(payload), strict=False)

    @staticmethod
    def create_review_comments(
        files: List[FileObj],
        tidy_tool: bool,
        summary_only: bool,
        review_comments: ReviewComments,
    ):
        """Creates a batch of comments for a specific clang tool's PR review.

        :param files: The list of files to traverse.
        :param tidy_tool: A flag to indicate if the suggestions should originate
            from clang-tidy.
        :param summary_only: A flag to indicate if only the review summary is desired.
        :param review_comments: An object (passed by reference) that is used to store
            the results.
        """
        for file_obj in files:
            tool_advice: Optional[PatchMixin]
            if tidy_tool:
                tool_advice = file_obj.tidy_advice
            else:
                tool_advice = file_obj.format_advice
            if not tool_advice:
                continue
            tool_advice.get_suggestions_from_patch(
                file_obj, summary_only, review_comments
            )

    def _dismiss_stale_reviews(self, url: str):
        """Dismiss all reviews that were previously created by cpp-linter"""
        next_page: Optional[str] = url + "?page=1&per_page=100"
        while next_page:
            response = self.api_request(url=next_page)
            next_page = self.has_more_pages(response)

            reviews: List[Dict[str, Any]] = response.json()
            for review in reviews:
                if (
                    "body" in review
                    and cast(str, review["body"]).startswith(COMMENT_MARKER)
                    and "state" in review
                    and review["state"] not in ["PENDING", "DISMISSED"]
                ):
                    assert "id" in review
                    self.api_request(
                        url=f"{url}/{review['id']}/dismissals",
                        method="PUT",
                        data=json.dumps(
                            {"message": "outdated suggestion", "event": "DISMISS"}
                        ),
                        strict=False,
                    )
