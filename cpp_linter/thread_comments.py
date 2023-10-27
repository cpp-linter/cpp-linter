"""A module to house the various functions for traversing/adjusting comments"""
from typing import Union, cast, List, Optional, Dict, Any
import json
from pathlib import Path
import requests
from . import (
    Globals,
    GlobalParser,
    logger,
    make_headers,
    GITHUB_SHA,
    log_response_msg,
    range_of_changed_lines,
    CACHE_PATH,
)


def update_comment(
    comments_url: str,
    user_id: int,
    count: int,
    no_lgtm: bool,
    update_only: bool,
    is_lgtm: bool,
):
    """Updates the comment for an existing comment or posts a new comment if
    ``update_only`` is `False`.


    :param comments_url: The URL used to fetch the comments.
    :param user_id: The user's account id number.
    :param count: The number of comments to traverse.
    :param update_only: A flag that describes if the outdated bot comment should only be
        updated (instead of replaced).
    :param no_lgtm: A flag to control if a "Looks Good To Me" comment should be posted.
        if this is `False`, then an outdated bot comment will still be deleted.
    """
    comment_url = remove_bot_comments(
        comments_url, user_id, count, delete=not update_only or (is_lgtm and no_lgtm)
    )
    if (is_lgtm and not no_lgtm) or not is_lgtm:
        if comment_url is not None:
            comments_url = comment_url
            req_meth = requests.patch
        else:
            req_meth = requests.post
        payload = json.dumps({"body": Globals.OUTPUT})
        logger.debug("payload body:\n%s", payload)
        Globals.response_buffer = req_meth(
            comments_url, headers=make_headers(), data=payload
        )
        logger.info(
            "Got %d response from %sing comment",
            Globals.response_buffer.status_code,
            "POST" if comment_url is None else "PATCH",
        )
        log_response_msg()


def remove_bot_comments(
    comments_url: str, user_id: int, count: int, delete: bool
) -> Optional[str]:
    """Traverse the list of comments made by a specific user
    and remove all.

    :param comments_url: The URL used to fetch the comments.
    :param user_id: The user's account id number.
    :param count: The number of comments to traverse.
    :param delete: A flag describing if first applicable bot comment should be deleted
        or not.

    :returns: If updating a comment, this will return the comment URL.
    """
    logger.info("comments_url: %s", comments_url)
    page = 1
    comment_url: Optional[str] = None
    while count:
        Globals.response_buffer = requests.get(comments_url + f"?page={page}")
        if not log_response_msg():
            return comment_url  # error getting comments for the thread; stop here
        comments = cast(List[Dict[str, Any]], Globals.response_buffer.json())
        json_comments = Path(f"{CACHE_PATH}/comments-pg{page}.json")
        json_comments.write_text(json.dumps(comments, indent=2), encoding="utf-8")

        page += 1
        count -= len(comments)
        for comment in comments:
            # only search for comments from the user's ID and
            # whose comment body begins with a specific html comment
            if (
                int(comment["user"]["id"]) == user_id
                # the specific html comment is our action's name
                and comment["body"].startswith("<!-- cpp linter action -->")
            ):
                logger.debug(
                    "comment id %d from user %s (%d)",
                    comment["id"],
                    comment["user"]["login"],
                    comment["user"]["id"],
                )
                if delete or (not delete and comment_url is not None):
                    # if not updating: remove all outdated comments
                    # if updating: remove all outdated comments except the last one

                    # use last saved comment_url (if not None) or current comment url
                    url = comment_url or comment["url"]
                    Globals.response_buffer = requests.delete(
                        url,
                        headers=make_headers(),
                    )
                    logger.info(
                        "Got %d from DELETE %s",
                        Globals.response_buffer.status_code,
                        url[url.find(".com") + 4 :],
                    )
                    log_response_msg()
                if not delete:
                    comment_url = cast(str, comment["url"])
    return comment_url


def aggregate_tidy_advice(lines_changed_only: int) -> List[Dict[str, Any]]:
    """Aggregate a list of json contents representing advice from clang-tidy
    suggestions.

    :param lines_changed_only: A flag indicating the focus of the advice that
        should be headed.
    """
    results = []
    for fixit, file in zip(GlobalParser.tidy_advice, Globals.FILES):
        for diag in fixit.diagnostics:
            ranges = range_of_changed_lines(file, lines_changed_only)
            if lines_changed_only and diag.line not in ranges:
                continue

            # base body of comment
            body = "<!-- cpp linter action -->\n## :speech_balloon: Clang-tidy\n**"
            body += diag.name + "**\n>" + diag.message

            # get original code
            filename = Path(cast(str, file["filename"]))
            # the list of lines in a file
            lines = filename.read_text(encoding="utf-8").splitlines()

            # aggregate clang-tidy advice
            suggestion = "\n```suggestion\n"
            is_multiline_fix = False
            fix_lines: List[int] = []  # a list of line numbers for the suggested fixes
            line = ""  # the line that concerns the fix/comment
            for i, tidy_fix in enumerate(diag.replacements):
                line = lines[tidy_fix.line - 1]
                if not fix_lines:
                    fix_lines.append(tidy_fix.line)
                elif tidy_fix.line not in fix_lines:
                    is_multiline_fix = True
                    break
                if i:  # if this isn't the first tidy_fix for the same line
                    last_fix = diag.replacements[i - 1]
                    suggestion += (
                        line[last_fix.cols + last_fix.null_len - 1 : tidy_fix.cols - 1]
                        + tidy_fix.text.decode()
                    )
                else:
                    suggestion += line[: tidy_fix.cols - 1] + tidy_fix.text.decode()
            if not is_multiline_fix and diag.replacements:
                # complete suggestion with original src code and closing md fence
                last_fix = diag.replacements[len(diag.replacements) - 1]
                suggestion += line[last_fix.cols + last_fix.null_len - 1 : -1] + "\n```"
                body += suggestion

            results.append(
                {
                    "body": body,
                    "commit_id": GITHUB_SHA,
                    "line": diag.line,
                    "path": fixit.filename,
                    "side": "RIGHT",
                }
            )
    return results


def aggregate_format_advice(lines_changed_only: int) -> List[Dict[str, Any]]:
    """Aggregate a list of json contents representing advice from clang-format
    suggestions.

    :param lines_changed_only: A flag indicating the focus of the advice that
        should be headed.
    """
    results = []
    for fmt_advice, file in zip(GlobalParser.format_advice, Globals.FILES):
        # get original code
        filename = Path(file["filename"])
        # the list of lines from the src file
        lines = filename.read_text(encoding="utf-8").splitlines()

        # aggregate clang-format suggestion
        line = ""  # the line that concerns the fix
        for fixed_line in fmt_advice.replaced_lines:
            # clang-format can include advice that starts/ends outside the diff's domain
            ranges = range_of_changed_lines(file, lines_changed_only)
            if lines_changed_only and fixed_line.line not in ranges:
                continue  # line is out of scope for diff, so skip this fix

            # assemble the suggestion
            body = "## :scroll: clang-format advice\n```suggestion\n"
            line = lines[fixed_line.line - 1]
            # logger.debug("%d >>> %s", fixed_line.line, line[:-1])
            for fix_index, line_fix in enumerate(fixed_line.replacements):
                # logger.debug(
                #     "%s >>> %s", repr(line_fix), line_fix.text.encode("utf-8")
                # )
                if fix_index:
                    last_fix = fixed_line.replacements[fix_index - 1]
                    body += line[
                        last_fix.cols + last_fix.null_len - 1 : line_fix.cols - 1
                    ]
                    body += line_fix.text
                else:
                    body += line[: line_fix.cols - 1] + line_fix.text
            # complete suggestion with original src code and closing md fence
            last_fix = fixed_line.replacements[-1]
            body += line[last_fix.cols + last_fix.null_len - 1 : -1] + "\n```"
            # logger.debug("body <<< %s", body)

            # create a suggestion from clang-format advice
            results.append(
                {
                    "body": body,
                    "commit_id": GITHUB_SHA,
                    "line": fixed_line.line,
                    "path": fmt_advice.filename,
                    "side": "RIGHT",
                }
            )
    return results


def concatenate_comments(
    tidy_advice: list, format_advice: list
) -> List[Dict[str, Union[str, int]]]:
    """Concatenate comments made to the same line of the same file.

    :param tidy_advice: Pass the output from `aggregate_tidy_advice()` here.
    :param format_advice: Pass the output from `aggregate_format_advice()` here.
    """
    # traverse comments from clang-format
    for index, comment_body in enumerate(format_advice):
        # check for comments from clang-tidy on the same line
        comment_index = None
        for i, payload in enumerate(tidy_advice):
            if (
                payload["line"] == comment_body["line"]
                and payload["path"] == comment_body["path"]
            ):
                comment_index = i  # mark this comment for concatenation
                break
        if comment_index is not None:
            # append clang-format advice to clang-tidy output/suggestion
            tidy_advice[comment_index]["body"] += "\n" + comment_body["body"]
            del format_advice[index]  # remove duplicate comment
    return tidy_advice + format_advice


def list_diff_comments(lines_changed_only: int) -> List[Dict[str, Union[str, int]]]:
    """Aggregate list of comments for use in the event's diff. This function assumes
    that the CLI option ``--lines_changed_only`` is set to True.

    :param lines_changed_only: A flag indicating the focus of the advice that
        should be headed.

    :returns:
        A list of comments (each element as json content).
    """
    return concatenate_comments(
        aggregate_tidy_advice(lines_changed_only),
        aggregate_format_advice(lines_changed_only),
    )


def get_review_id(reviews_url: str, user_id: int) -> Optional[int]:
    """Dismiss all stale reviews (only the ones made by our bot).

    :param reviews_url: The URL used to fetch the review comments.
    :param user_id: The user's account id number.

    :returns:
        The ID number of the review created by the action's generic bot.
    """
    logger.info("  review_url: %s", reviews_url)
    Globals.response_buffer = requests.get(reviews_url)
    review_id = find_review(json.loads(Globals.response_buffer.text), user_id)
    if review_id is None:  # create a PR review
        Globals.response_buffer = requests.post(
            reviews_url,
            headers=make_headers(),
            data=json.dumps(
                {
                    "body": "<!-- cpp linter action -->\n"
                    "CPP Linter Action found no problems",
                    "event": "COMMENTED",
                }
            ),
        )
        logger.info(
            "Got %d from POSTing new(/temp) PR review",
            Globals.response_buffer.status_code,
        )
        Globals.response_buffer = requests.get(reviews_url)
        if Globals.response_buffer.status_code != 200 and log_response_msg():
            raise RuntimeError("could not create a review for comments")
        reviews = json.loads(Globals.response_buffer.text)
        reviews.reverse()  # traverse the list in reverse
        review_id = find_review(reviews, user_id)
    return review_id


def find_review(reviews: dict, user_id: int) -> Optional[int]:
    """Find a review created by a certain user ID.

    :param reviews: the JSON object fetched via GIT REST API.
    :param user_id: The user account's ID number

    :returns:
        An ID that corresponds to the specified ``user_id``.
    """
    review_id = None
    for review in reviews:
        if int(review["user"]["id"]) == user_id and review["body"].startswith(
            "<!-- cpp linter action -->"
        ):
            review_id = int(review["id"])
            break  # there will only be 1 review from this action, so break when found

    logger.info("   review_id: %d", review_id)
    return review_id
