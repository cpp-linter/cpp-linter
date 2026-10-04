"""Everything cpp-linter needs to talk to a git server.

All network interaction is delegated to a ``git_bot_feedback.GitClient``. This module
only adds the cpp-linter specific bits: constants, the markdown comment/summary
formats, and the assembly of PR reviews.
"""

from os import environ
from pathlib import Path, PurePath
import sys

import git_bot_feedback as gbf
from git_bot_feedback import (
    AnnotationLevel,
    CommentKind,
    CommentPolicy,
    FileAnnotation,
    GitClient,
    OutputVariable,
    ReviewAction,
    ReviewComment,
    ReviewOptions,
    ThreadCommentOptions,
)

from ._version import version
from .clang_tools import ClangVersions
from .clang_tools.clang_format import formalize_style_name, tally_format_advice
from .clang_tools.clang_tidy import tally_tidy_advice
from .clang_tools.patcher import PatchMixin, ReviewComments
from .cli import Args
from .common_fs import FileObj
from .git import get_list_of_changed_files
from .loggers import log_commander, logger

USER_OUTREACH = (
    "\n\nHave any feedback or feature suggestions? [Share it here.]"
    + "(https://github.com/cpp-linter/cpp-linter-action/issues)"
)
COMMENT_MARKER = "<!-- cpp linter action -->\n"
USER_AGENT = f"cpp-linter/{version}"

#: The maximum length of a thread comment.
THREAD_COMMENT_LIMIT = 65535


def make_comment(
    files: list[FileObj],
    format_checks_failed: int,
    tidy_checks_failed: int,
    clang_versions: ClangVersions,
    len_limit: None | int = None,
) -> str:
    """Make a markdown comment from the given advice.

    :param files: A list of objects, each describing a file's information.
    :param format_checks_failed: The amount of clang-format checks that have failed.
    :param tidy_checks_failed: The amount of clang-tidy checks that have failed.
    :param clang_versions: The versions of the clang tools used.
    :param len_limit: The length limit of the comment generated.

    :returns: The markdown comment as a `str`
    """
    opener = f"{COMMENT_MARKER}# Cpp-Linter Report "
    comment = ""

    def adjust_limit(limit: int | None, text: str) -> int | None:
        if limit is not None:
            return limit - len(text)
        return limit

    for text in (opener, USER_OUTREACH):
        len_limit = adjust_limit(limit=len_limit, text=text)

    if format_checks_failed or tidy_checks_failed:
        prefix = ":warning:\nSome files did not pass the configured checks!\n"
        len_limit = adjust_limit(limit=len_limit, text=prefix)
        if format_checks_failed:
            comment += _make_format_comment(
                files=files,
                checks_failed=format_checks_failed,
                len_limit=len_limit,
                version=clang_versions.format,
            )
        if tidy_checks_failed:
            comment += _make_tidy_comment(
                files=files,
                checks_failed=tidy_checks_failed,
                len_limit=adjust_limit(limit=len_limit, text=comment),
                version=clang_versions.tidy,
            )
    else:
        prefix = ":heavy_check_mark:\nNo problems need attention."
    return opener + prefix + comment + USER_OUTREACH


def _make_format_comment(
    files: list[FileObj],
    checks_failed: int,
    len_limit: None | int = None,
    version: None | str = None,
) -> str:
    """make a comment describing clang-format errors"""
    comment = "\n<details><summary>clang-format{} reports: <strong>".format(
        "" if version is None else f" (v{version})"
    )
    comment += f"{checks_failed} file(s) not formatted</strong></summary>\n\n"
    closer = "\n</details>"
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


def _make_tidy_comment(
    files: list[FileObj],
    checks_failed: int,
    len_limit: None | int = None,
    version: None | str = None,
) -> str:
    """make a comment describing clang-tidy errors"""
    comment = "\n<details><summary>clang-tidy{} reports: <strong>".format(
        "" if version is None else f" (v{version})"
    )
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
                tidy_comment += "{severity}: [{diagnostic}]\n   > {rationale}\n".format(
                    severity=note.severity,
                    diagnostic=note.diagnostic_link,
                    rationale=note.rationale,
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


def create_review_comments(
    files: list[FileObj],
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
    tool_name = "clang-tidy" if tidy_tool else "clang-format"
    review_comments.tool_total[tool_name] = 0
    for file_obj in files:
        tool_advice: None | PatchMixin
        if tidy_tool:
            tool_advice = file_obj.tidy_advice
        else:
            tool_advice = file_obj.format_advice
        if not tool_advice:
            continue
        tool_advice.get_suggestions_from_patch(file_obj, summary_only, review_comments)


def make_annotations(files: list[FileObj], style: str) -> list[FileAnnotation]:
    """Create annotations from the clang tools' advice."""
    annotations: list[FileAnnotation] = []
    style_guide = formalize_style_name(style)
    for file_obj in files:
        name = file_obj.name
        if file_obj.format_advice and file_obj.format_advice.replaced_lines:
            line_list = ", ".join(
                str(fix.line) for fix in file_obj.format_advice.replaced_lines
            )
            annotations.append(
                FileAnnotation(
                    severity=AnnotationLevel.Notice,
                    path=name,
                    title=f"Run clang-format on {name}",
                    message=f"File {name} does not conform to {style_guide} "
                    + f"style guidelines. (lines {line_list})",
                )
            )
        if file_obj.tidy_advice:
            for note in file_obj.tidy_advice.notes:
                if note.filename != name:
                    continue
                if note.severity.startswith("note"):
                    severity = AnnotationLevel.Notice
                elif note.severity.startswith("error"):
                    severity = AnnotationLevel.Error
                else:
                    severity = AnnotationLevel.Warning
                annotations.append(
                    FileAnnotation(
                        severity=severity,
                        path=name,
                        start_line=int(note.line),
                        end_line=int(note.line),
                        start_column=int(note.cols),
                        title=f"{name}:{note.line}:",
                        message=f"{note.cols} [{note.diagnostic}]::{note.rationale}",
                    )
                )
    return annotations


class LinterClient:
    """A thin wrapper of `git_bot_feedback.GitClient` that knows how to deliver
    cpp-linter's results.

    :param git_client: A client to delegate to. If not provided, then one is
        created (and configured with cpp-linter's user agent).
    """

    def __init__(self, git_client: GitClient | None = None) -> None:
        if git_client is None:
            git_client = GitClient()
            git_client.set_user_agent(USER_AGENT)
        self._client = git_client

    @property
    def event_name(self) -> str:
        """The triggering event type's name."""
        return self._client.event_name or "unknown"

    @property
    def is_pr_event(self) -> bool:
        """Is the triggering event a pull request?"""
        return self._client.is_pr_event()

    @property
    def debug_enabled(self) -> bool:
        """Are debug logs enabled on the CI runner?"""
        return self._client.is_debug_enabled()

    @property
    def has_token(self) -> bool:
        """Is the token required to post comments/reviews available?"""
        kind = self._client.client_kind
        return (kind == "github" and "GITHUB_TOKEN" in environ) or (
            kind == "gitea" and "GITEA_TOKEN" in environ
        )

    async def get_changed_files(
        self,
        file_filter: gbf.FileFilter,
        lines_changed_only: int,
        diff_base: None | int | str = None,
        ignore_index: bool = False,
    ) -> list[FileObj]:
        """Fetch a list of the event's changed files.

        :param file_filter: A `git_bot_feedback.FileFilter` to filter files.
        :param lines_changed_only: A value that dictates what file changes to focus on.
        :param diff_base: The commit or ref to use as the base of the diff.
        :param ignore_index: Setting this flag to `True` will ignore any staged changes
            in the index when producing a diff.
        """
        return await get_list_of_changed_files(
            file_filter=file_filter,
            lines_changed_only=lines_changed_only,
            diff_base=diff_base,
            ignore_index=ignore_index,
            git_client=self._client,
        )

    def set_exit_code(
        self,
        checks_failed: int,
        format_checks_failed: int | None = None,
        tidy_checks_failed: int | None = None,
    ) -> int:
        """Set the action's output values and show them in the log output.

        :returns: The ``checks_failed`` parameter.
        """
        self._client.write_output_variables(
            [
                OutputVariable(name="checks-failed", value=str(checks_failed)),
                OutputVariable(
                    name="clang-format-checks-failed",
                    value=str(format_checks_failed or 0),
                ),
                OutputVariable(
                    name="clang-tidy-checks-failed",
                    value=str(tidy_checks_failed or 0),
                ),
            ]
        )
        logger.info("%d clang-format-checks-failed", format_checks_failed or 0)
        logger.info("%d clang-tidy-checks-failed", tidy_checks_failed or 0)
        logger.info("%d checks-failed", checks_failed)
        return checks_failed

    async def post_feedback(
        self,
        files: list[FileObj],
        args: Args,
        clang_versions: ClangVersions,
    ) -> int:
        """Post the results according to the user's CLI options.

        :param files: A list of objects, each describing a file's information.
        :param args: A namespace of arguments parsed from the :doc:`CLI <../cli_args>`.
        :param clang_versions: The version of the clang tools used.

        :returns: The total number of checks that failed.
        """
        format_checks_failed = tally_format_advice(files)
        tidy_checks_failed = tally_tidy_advice(files)
        checks_failed = format_checks_failed + tidy_checks_failed

        def comment_with_limit(len_limit: int | None) -> str:
            return make_comment(
                files=files,
                format_checks_failed=format_checks_failed,
                tidy_checks_failed=tidy_checks_failed,
                clang_versions=clang_versions,
                len_limit=len_limit,
            )

        # the step summary has no length limit
        comment: str | None = None
        if args.step_summary or args.summary_output_file:
            comment = comment_with_limit(None)
            if args.step_summary:
                self._client.append_step_summary(comment)
            if args.summary_output_file:
                self._write_summary_file(args.summary_output_file, comment)

        if args.file_annotations:
            annotations = make_annotations(files, args.style)
            if annotations:
                self._client.write_file_annotations(annotations)

        self.set_exit_code(checks_failed, format_checks_failed, tidy_checks_failed)

        if args.thread_comments != "false":
            if not self.has_token:
                logger.error("The token is required to post comments!")
                sys.exit(1)
            if comment is None or len(comment) >= THREAD_COMMENT_LIMIT:
                comment = comment_with_limit(THREAD_COMMENT_LIMIT)
            await self._client.post_thread_comment(
                ThreadCommentOptions(
                    policy=CommentPolicy.Update
                    if args.thread_comments == "update"
                    else CommentPolicy.Anew,
                    comment=comment,
                    kind=CommentKind.Lgtm
                    if not checks_failed
                    else CommentKind.Concerns,
                    marker=COMMENT_MARKER,
                    no_lgtm=args.no_lgtm,
                )
            )

        if self.is_pr_event and (args.tidy_review or args.format_review):
            if not self.has_token:
                logger.error("A token is required to post review comments!")
                sys.exit(1)
            await self._post_review(files, args, clang_versions)
        return checks_failed

    @staticmethod
    def _write_summary_file(path: str, comment: str):
        output_path = Path(path).resolve()
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(f"\n{comment}\n", encoding="utf-8")
        except (OSError, ValueError) as exc:
            log_commander.error(
                "Failed to write summary output file '%s': %s", output_path, exc
            )

    async def _post_review(
        self, files: list[FileObj], args: Args, clang_versions: ClangVersions
    ):
        """Assemble all review comments, cull the ones already posted, then post
        a review whose summary describes what remains."""
        summary_only = environ.get(
            "CPP_LINTER_PR_REVIEW_SUMMARY_ONLY", "false"
        ).lower() in ("true", "on", "1")
        review_comments = ReviewComments()
        if args.format_review:
            create_review_comments(files, False, summary_only, review_comments)
        if args.tidy_review:
            create_review_comments(files, True, summary_only, review_comments)

        is_lgtm = not sum(
            x for x in review_comments.tool_total.values() if isinstance(x, int)
        )
        if is_lgtm:
            if args.no_lgtm:
                logger.debug("Not posting an approved review because `no-lgtm` is true")
                return
            action = ReviewAction.Approve
        else:
            action = ReviewAction.RequestChanges
        if args.passive_reviews:
            action = ReviewAction.Comment

        rc_list = (
            []
            if summary_only
            else [
                ReviewComment(
                    path=sug.file_name,
                    comment=sug.comment,
                    line_end=sug.line_end,
                    line_start=sug.line_start
                    if sug.line_start != sug.line_end and sug.line_start > 0
                    else None,
                )
                for sug in review_comments.suggestions
            ]
        )
        options = ReviewOptions(
            comments=rc_list,
            action=action,
            summary="",
            marker=COMMENT_MARKER,
            allow_draft=False,
            allow_closed=False,
            delete_review_comments=args.passive_reviews,
        )
        culled = await self._client.cull_pr_reviews(options)

        summary, _ = review_comments.serialize_to_github_payload(
            tidy_version=clang_versions.tidy,
            format_version=clang_versions.format,
            reused=len(rc_list) - len(culled.comments),
        )
        body = f"{COMMENT_MARKER}## Cpp-linter Review\n{summary}"
        if is_lgtm:
            body += "\nGreat job! :tada:"
        culled.summary = body + USER_OUTREACH
        await self._client.post_pr_review(culled)
