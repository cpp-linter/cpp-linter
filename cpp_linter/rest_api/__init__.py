"""This base module holds abstractions common to using REST API.
See other modules in ``rest_api`` subpackage for detailed derivatives.
"""

from abc import ABC
from pathlib import PurePath
import sys
import time
from typing import Optional, Dict, List, Any, cast, NamedTuple
import requests
from ..common_fs import FileObj
from ..common_fs.file_filter import FileFilter
from ..cli import Args
from ..loggers import logger, log_response_msg


USER_OUTREACH = (
    "\n\nHave any feedback or feature suggestions? [Share it here.]"
    + "(https://github.com/cpp-linter/cpp-linter-action/issues)"
)
COMMENT_MARKER = "<!-- cpp linter action -->\n"


class RateLimitHeaders(NamedTuple):
    """A collection of HTTP response header keys that describe a REST API's rate limits.
    Each parameter corresponds to a instance attribute (see below)."""

    reset: str  #: The header key of the rate limit's reset time.
    remaining: str  #: The header key of the rate limit's remaining attempts.
    retry: str  #: The header key of the rate limit's "backoff" time interval.


class RestApiClient(ABC):
    """A class that describes the API used to interact with a git server's REST API.

    :param rate_limit_headers: See `RateLimitHeaders` class.
    """

    def __init__(self, rate_limit_headers: RateLimitHeaders) -> None:
        self.session = requests.Session()

        # The remain API requests allowed under the given token (if any).
        self._rate_limit_remaining = -1  # -1 means unknown
        # a counter for avoiding secondary rate limits
        self._rate_limit_back_step = 0
        # the rate limit reset time
        self._rate_limit_reset: Optional[time.struct_time] = None
        # the rate limit HTTP response header keys
        self._rate_limit_headers = rate_limit_headers

    def _rate_limit_exceeded(self):
        logger.error("RATE LIMIT EXCEEDED!")
        if self._rate_limit_reset is not None:
            logger.error(
                "Gitlab REST API rate limit resets on %s",
                time.strftime("%d %B %Y %H:%M +0000", self._rate_limit_reset),
            )
        sys.exit(1)

    def api_request(
        self,
        url: str,
        method: Optional[str] = None,
        data: Optional[str] = None,
        headers: Optional[Dict[str, Any]] = None,
        strict: bool = True,
    ) -> requests.Response:
        """A helper function to streamline handling of HTTP requests' responses.

        :param url: The  HTTP request URL.
        :param method: The HTTP request method. The default value `None` means
            "GET" if ``data`` is `None` else "POST"
        :param data: The HTTP request payload data.
        :param headers: The HTTP request headers to use. This can be used to override
            the default headers used.
        :param strict: If this is set `True`, then an :py:class:`~requests.HTTPError`
            will be raised when the HTTP request responds with a status code greater
            than or equal to 400.

        :returns:
            The HTTP request's response object.
        """
        if self._rate_limit_back_step >= 5 or self._rate_limit_remaining == 0:
            self._rate_limit_exceeded()
        response = self.session.request(
            method=method or ("GET" if data is None else "POST"),
            url=url,
            headers=headers,
            data=data,
        )
        self._rate_limit_remaining = int(
            response.headers.get(self._rate_limit_headers.remaining, "-1")
        )
        if self._rate_limit_headers.reset in response.headers:
            self._rate_limit_reset = time.gmtime(
                int(response.headers[self._rate_limit_headers.reset])
            )
        log_response_msg(response)
        if response.status_code in [403, 429]:  # rate limit exceeded
            # secondary rate limit handling
            if self._rate_limit_headers.retry in response.headers:
                wait_time = (
                    float(
                        cast(str, response.headers.get(self._rate_limit_headers.retry))
                    )
                    * self._rate_limit_back_step
                )
                logger.warning(
                    "SECONDARY RATE LIMIT HIT! Backing off for %f seconds",
                    wait_time,
                )
                time.sleep(wait_time)
                self._rate_limit_back_step += 1
                return self.api_request(url, method=method, data=data, headers=headers)
            # primary rate limit handling
            if self._rate_limit_remaining == 0:
                self._rate_limit_exceeded()
        if strict:
            response.raise_for_status()
        self._rate_limit_back_step = 0
        return response

    def set_exit_code(
        self,
        checks_failed: int,
        format_checks_failed: Optional[int] = None,
        tidy_checks_failed: Optional[int] = None,
    ):
        """Set the action's output values and shows them in the log output.

        :param checks_failed: A int describing the total number of checks that failed.
        :param format_checks_failed: A int describing the number of checks that failed
            only for clang-format.
        :param tidy_checks_failed: A int describing the number of checks that failed
            only for clang-tidy.

        :returns:
            The ``checks_failed`` parameter was not passed.
        """
        logger.info("%d clang-format-checks-failed", format_checks_failed or 0)
        logger.info("%d clang-tidy-checks-failed", tidy_checks_failed or 0)
        logger.info("%d checks-failed", checks_failed)
        return checks_failed

    def make_headers(self, use_diff: bool = False) -> Dict[str, str]:
        """Create a `dict` for use in REST API headers.

        :param use_diff: A flag to indicate that the returned format should be in diff
            syntax.
        :returns: A `dict` to be used as headers in `requests` API calls.
        """
        raise NotImplementedError("must be implemented in the derivative")

    def get_list_of_changed_files(
        self,
        file_filter: FileFilter,
        lines_changed_only: int,
    ) -> List[FileObj]:
        """Fetch a list of the event's changed files.

        :param file_filter: A `FileFilter` obj to filter files.
        :param lines_changed_only: A value that dictates what file changes to focus on.
        """
        raise NotImplementedError("must be implemented in the derivative")

    @staticmethod
    def make_comment(
        files: List[FileObj],
        format_checks_failed: int,
        tidy_checks_failed: int,
        len_limit: Optional[int] = None,
    ) -> str:
        """Make an MarkDown comment from the given advice. Also returns a count of
        checks failed for each tool (clang-format and clang-tidy)

        :param files: A list of objects, each describing a file's information.
        :param format_checks_failed: The amount of clang-format checks that have failed.
        :param tidy_checks_failed: The amount of clang-tidy checks that have failed.
        :param len_limit: The length limit of the comment generated.

        :Returns: The markdown comment as a `str`
        """
        opener = f"{COMMENT_MARKER}# Cpp-Linter Report "
        comment = ""

        def adjust_limit(limit: Optional[int], text: str) -> Optional[int]:
            if limit is not None:
                return limit - len(text)
            return limit

        for text in (opener, USER_OUTREACH):
            len_limit = adjust_limit(limit=len_limit, text=text)

        if format_checks_failed or tidy_checks_failed:
            prefix = ":warning:\nSome files did not pass the configured checks!\n"
            len_limit = adjust_limit(limit=len_limit, text=prefix)
            if format_checks_failed:
                comment += RestApiClient._make_format_comment(
                    files=files,
                    checks_failed=format_checks_failed,
                    len_limit=len_limit,
                )
            if tidy_checks_failed:
                comment += RestApiClient._make_tidy_comment(
                    files=files,
                    checks_failed=tidy_checks_failed,
                    len_limit=adjust_limit(limit=len_limit, text=comment),
                )
        else:
            prefix = ":heavy_check_mark:\nNo problems need attention."
        return opener + prefix + comment + USER_OUTREACH

    @staticmethod
    def _make_format_comment(
        files: List[FileObj],
        checks_failed: int,
        len_limit: Optional[int] = None,
    ) -> str:
        """make a comment describing clang-format errors"""
        comment = "\n<details><summary>clang-format reports: <strong>"
        comment += f"{checks_failed} file(s) not formatted</strong></summary>\n\n"
        closer = "\n</details>"
        checks_failed = 0
        for file_obj in files:
            if not file_obj.format_advice:
                continue
            if file_obj.format_advice.replaced_lines:
                format_comment = f"- {file_obj.name}\n"
                if (
                    len_limit is None
                    or len(comment) + len(closer) + len(format_comment) < len_limit
                ):
                    comment += format_comment
        return comment + closer

    @staticmethod
    def _make_tidy_comment(
        files: List[FileObj],
        checks_failed: int,
        len_limit: Optional[int] = None,
    ) -> str:
        """make a comment describing clang-tidy errors"""
        comment = "\n<details><summary>clang-tidy reports: <strong>"
        comment += f"{checks_failed} concern(s)</strong></summary>\n\n"
        closer = "\n</details>"
        for file_obj in files:
            if not file_obj.tidy_advice:
                continue
            for note in file_obj.tidy_advice.notes:
                if file_obj.name == note.filename:
                    tidy_comment = "- **{filename}:{line}:{cols}:** ".format(
                        filename=file_obj.name,
                        line=note.line,
                        cols=note.cols,
                    )
                    tidy_comment += (
                        "{severity}: [{diagnostic}]\n   > {rationale}\n".format(
                            severity=note.severity,
                            diagnostic=note.diagnostic_link,
                            rationale=note.rationale,
                        )
                    )
                    if note.fixit_lines:
                        ext = PurePath(file_obj.name).suffix.lstrip(".")
                        suggestion = "\n   ".join(note.fixit_lines)
                        tidy_comment += f"\n   ```{ext}\n   {suggestion}\n   ```\n"

                    if (
                        len_limit is None
                        or len(comment) + len(closer) + len(tidy_comment) < len_limit
                    ):
                        comment += tidy_comment
        return comment + closer

    def post_feedback(
        self,
        files: List[FileObj],
        args: Args,
    ):
        """Post action's results using REST API.

        :param files: A list of objects, each describing a file's information.
        :param args: A namespace of arguments parsed from the :doc:`CLI <../cli_args>`.
        """
        raise NotImplementedError("Must be defined in the derivative")

    @staticmethod
    def has_more_pages(response: requests.Response) -> Optional[str]:
        """A helper function to parse a HTTP request's response headers to determine if
        the previous REST API call is paginated.

        :param response: A HTTP request's response.

        :returns: The URL of the next page if any, otherwise `None`.
        """
        links = response.links
        if "next" in links and "url" in links["next"]:
            return links["next"]["url"]
        return None
