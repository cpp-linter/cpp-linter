"""Tests that complete coverage that aren't prone to failure."""

import json
import logging
import os
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from git_bot_feedback import AnnotationLevel
from mock_server import MockServer, RecordedRequest

import cpp_linter
from cpp_linter.clang_tools import ClangVersions, assemble_version_exec, patcher
from cpp_linter.clang_tools.clang_tidy import TidyNotification
from cpp_linter.clang_tools.patcher import PatchMixin, ReviewComments, Suggestion
from cpp_linter.cli import Args
from cpp_linter.common_fs import FileObj, get_line_cnt_from_cols
from cpp_linter.common_fs.file_filter import list_source_files, make_file_filter
from cpp_linter.loggers import (
    log_commander,
    logger,
    worker_log_init,
)
from cpp_linter.rest_api import (
    LinterClient,
    create_review_comments,
    make_annotations,
    make_comment,
)


@pytest.mark.no_clang
def test_exit_output(mock_server: MockServer, monkeypatch: pytest.MonkeyPatch):
    """Test exit code that indicates if action encountered lining errors."""
    monkeypatch.setenv("GITHUB_REPOSITORY", "cpp-linter/test-repo")
    monkeypatch.setenv("GITHUB_SHA", "deadbeef")
    env_file = Path(os.environ["GITHUB_OUTPUT"])
    gh_client = LinterClient()
    tidy_checks_failed = 1
    format_checks_failed = 2
    checks_failed = 3
    assert 3 == gh_client.set_exit_code(
        checks_failed, format_checks_failed, tidy_checks_failed
    )
    output = env_file.read_text(encoding="utf-8")
    assert f"checks-failed={checks_failed}\n" in output
    assert f"format-checks-failed={format_checks_failed}\n" in output
    assert f"tidy-checks-failed={tidy_checks_failed}\n" in output


# see https://github.com/pytest-dev/pytest/issues/5997
@pytest.mark.no_clang
@pytest.mark.parametrize("github_actions", ["true", ""])
def test_end_group(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    github_actions: str,
):
    """Test the output that concludes a group of runner logs."""
    monkeypatch.setenv("GITHUB_ACTIONS", github_actions)
    monkeypatch.setenv("GITHUB_REPOSITORY", "cpp-linter/test-repo")
    monkeypatch.setenv("GITHUB_SHA", "deadbeef")
    caplog.set_level(logging.INFO, logger=log_commander.name)
    log_commander.propagate = True
    client = LinterClient()
    client.end_log_group("group name")
    messages = caplog.messages
    for message in messages:
        if github_actions and message == "::endgroup::":
            break
        if not github_actions and message.endswith("group name"):
            break
    else:  # pragma: no cover
        raise AssertionError(f"Expected log group end not found in {caplog.messages}")


# see https://github.com/pytest-dev/pytest/issues/5997
@pytest.mark.no_clang
@pytest.mark.parametrize("github_actions", ["true", ""])
def test_start_group(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    github_actions: str,
):
    """Test the output that begins a group of runner logs."""
    monkeypatch.setenv("GITHUB_ACTIONS", github_actions)
    monkeypatch.setenv("GITHUB_REPOSITORY", "cpp-linter/test-repo")
    monkeypatch.setenv("GITHUB_SHA", "deadbeef")
    caplog.set_level(logging.INFO, logger=log_commander.name)
    log_commander.propagate = True
    client = LinterClient()
    client.start_log_group("TEST")
    messages = caplog.messages
    for message in messages:
        if github_actions and message == "::group::TEST":
            break
        if not github_actions and message.endswith("TEST"):
            break
    else:  # pragma: no cover
        raise AssertionError(f"Expected log group start not found in {messages}")


@pytest.mark.no_clang
def test_worker_log_init_resolves_rich(monkeypatch: pytest.MonkeyPatch):
    """``worker_log_init(use_rich=None)`` decides the rich setting itself."""
    # Workers normally receive `use_rich` from the parent, but the `None` default
    # must still fall back to `should_use_rich()`. Force the non-rich branch so
    # the test does not depend on whether `rich` is installed, and restore the
    # shared logger afterwards.
    monkeypatch.setenv("CPP_LINTER_PYTEST_NO_RICH", "1")
    saved_handlers = logger.handlers[:]
    saved_level = logger.level
    saved_propagate = logger.propagate
    try:
        log_stream = worker_log_init(logging.DEBUG, use_rich=None)
        logger.info("hello from worker")
        assert "hello from worker" in log_stream.getvalue()
        assert logger.level == logging.DEBUG
    finally:
        logger.handlers.clear()
        logger.handlers.extend(saved_handlers)
        logger.setLevel(saved_level)
        logger.propagate = saved_propagate


@pytest.mark.parametrize(
    "extensions",
    [
        (["cpp", "hpp", "yml"]),  # yml included to traverse .github folder
        pytest.param(["cxx"], marks=pytest.mark.xfail),
    ],
)
@pytest.mark.no_clang
def test_list_src_files(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    extensions: list[str],
):
    """List the source files in the root folder of this repo."""
    monkeypatch.chdir(Path(__file__).parent.parent.as_posix())
    caplog.set_level(logging.DEBUG, logger=logger.name)
    files = list_source_files(make_file_filter(extensions=extensions))
    assert files
    for file in files:
        assert Path(file.name).suffix.lstrip(".") in extensions


@pytest.mark.no_clang
@pytest.mark.parametrize("line,cols,offset", [(13, 5, 144), (19, 1, 189)])
def test_file_offset_translation(line: int, cols: int, offset: int):
    """Validate output from ``get_line_cnt_from_cols()``"""
    contents = Path("tests/demo/demo.cpp").read_bytes()
    assert (line, cols) == get_line_cnt_from_cols(contents, offset)


@pytest.mark.no_clang
def test_serialize_file_obj():
    """Validate JSON serialization of a FileObj instance."""
    file_obj = FileObj("some_name", [5, 10], [[2, 12]])
    json_obj = (
        r'[{"filename": "some_name", "line_filter": {"diff_chunks": [[2, 12]], '
        + r'"lines_added": [[5, 5], [10, 10]]}}]'
    )
    assert json.dumps([file_obj.serialize()]) == json_obj


CLANG_VERSION = os.getenv("CLANG_VERSION", "12")

DEFAULT_CLANG_FORMAT_EXE = cast(str, shutil.which("clang-format"))


@pytest.mark.parametrize("tool_name", ["clang-format"])
@pytest.mark.parametrize(
    "version",
    [
        CLANG_VERSION,
        str(Path(DEFAULT_CLANG_FORMAT_EXE).parent),
        str(Path(DEFAULT_CLANG_FORMAT_EXE).parent.parent),
        "",
    ],
    ids=["number", "path", "distant_parent_path", "none"],
)
def test_tool_exe_path(tool_name: str, version: str):
    """Test specifying the version of the clang tool."""
    exe_path = assemble_version_exec(tool_name, version)
    assert exe_path
    assert tool_name in exe_path


def test_clang_analyzer_link():
    """Ensures the hyper link for a diagnostic about clang-analyzer checks is
    not malformed"""
    file_name = "RF24.cpp"
    line = "1504"
    column = "9"
    rationale = "Dereference of null pointer (loaded from variable 'pipe_num')"
    severity = "warning"
    diagnostic_name = "clang-analyzer-core.NullDereference"
    note = TidyNotification(
        (
            file_name,
            line,
            column,
            severity,
            rationale,
            diagnostic_name,
        )
    )
    assert note.diagnostic_link == (
        "[{}]({}/{}.html)".format(
            diagnostic_name,
            "https://clang.llvm.org/extra/clang-tidy/checks/clang-analyzer",
            diagnostic_name.split("-", maxsplit=2)[2],
        )
    )


@pytest.mark.no_clang
def test_diagnostic_link_no_hyphen() -> None:
    """Test that diagnostic_link returns diagnostic name if no hyphen is present."""
    note = TidyNotification(
        (
            "test.cpp",
            1,
            1,
            "error",
            "Test rationale",
            "no_diagnostic_name",
        )
    )
    assert note.diagnostic_link == "no_diagnostic_name"


@pytest.mark.no_clang
def test_rest_api_skips_files_without_advice():
    """Missing format and tidy advice is ignored in comments and reviews."""
    file_obj = FileObj("src/main.cpp")
    clang_versions = ClangVersions()
    clang_versions.format = "18"
    clang_versions.tidy = "18"
    comment = make_comment([file_obj], 1, 1, clang_versions)
    assert "clang-format" in comment
    assert "clang-tidy" in comment
    assert "src/main.cpp" not in comment

    review = ReviewComments()
    create_review_comments([file_obj], False, False, review)
    create_review_comments([file_obj], True, False, review)
    assert review.tool_total == {"clang-tidy": 0, "clang-format": 0}
    assert not review.suggestions


@pytest.mark.no_clang
def test_make_annotations_skips_mismatched_tidy_note():
    """Only notes for this file become annotations, including note severity."""
    file_obj = FileObj("src/main.cpp")
    file_obj.tidy_advice = SimpleNamespace(
        notes=[
            SimpleNamespace(
                filename="src/other.cpp",
                severity="warning",
                line="2",
                cols="1",
                diagnostic="check-name",
                rationale="not this file",
            ),
            SimpleNamespace(
                filename="src/main.cpp",
                severity="note",
                line="3",
                cols="4",
                diagnostic="check-name",
                rationale="informational note",
            ),
        ]
    )

    annotations = make_annotations([file_obj], "llvm")

    assert len(annotations) == 1
    assert annotations[0].severity == AnnotationLevel.Notice
    assert annotations[0].start_line == 3


@pytest.mark.no_clang
def test_linter_client_properties_with_empty_event_name():
    """Client properties expose defaults and delegate the remaining values."""

    class GitClient:
        event_name = None
        client_kind = "local"

        def is_debug_enabled(self):
            return False

    client = LinterClient(GitClient())

    assert client.event_name == "unknown"
    assert client.debug_enabled is False
    assert client.client_kind == "local"


@pytest.mark.no_clang
def test_review_summary_reports_non_diff_suggestion():
    """A partial review summary reports concerns that did not fit the diff."""
    suggestion = Suggestion("src/main.cpp")
    suggestion.line_end = 4
    suggestion.comment = "### clang-format\nformat issue"
    review = ReviewComments()
    review.suggestions.append(suggestion)
    review.tool_total["clang-format"] = 2
    review.full_patch["clang-format"] = "- old line\n+ new line"

    summary, comments = review.serialize_to_github_payload(None, "18", reused=1)

    assert len(comments) == 1
    assert "Only 1 out of 2 clang-format concerns fit" in summary
    assert "1 review comment(s) from a previous review were reused" in summary


@pytest.mark.no_clang
def test_removal_only_patch_creates_suggestion(monkeypatch: pytest.MonkeyPatch):
    """A patch that only deletes lines produces a remove-line suggestion."""
    hunk = SimpleNamespace(lines=[SimpleNamespace(origin="-", old_lineno=7)])
    patch = SimpleNamespace(text="removal diff", hunks=[hunk])

    class PatchFactory:
        @staticmethod
        def create_from(*args, **kwargs):
            return patch

    class FormatPatch(PatchMixin):
        def get_tool_name(self):
            return "clang-format"

    monkeypatch.setattr(patcher, "Patch", PatchFactory)
    file_obj = FileObj("src/main.cpp")
    monkeypatch.setattr(file_obj, "read_with_timeout", lambda: b"")
    monkeypatch.setattr(file_obj, "is_hunk_contained", lambda _: (7, 7))
    advice = FormatPatch()
    advice.patched = b"diff"
    review = ReviewComments()

    advice.get_suggestions_from_patch(file_obj, False, review)

    assert review.tool_total["clang-format"] == 1
    assert "Please remove the line(s)" in review.suggestions[0].comment
    assert "- 7" in review.suggestions[0].comment


@pytest.mark.no_clang
def test_mock_server_request_helpers_and_route_mismatch():
    """Request helpers handle absent queries and route mismatches."""
    request = RecordedRequest(
        method="GET",
        path="/files",
        query="",
        headers={},
        body=b'{"count": 1}',
    )
    assert request.url == "/files"
    assert request.json() == {"count": 1}

    server = MockServer()
    server.get("/files", accept="application/json")
    unmatched = RecordedRequest(
        method="GET", path="/files", query="", headers={}, body=b""
    )
    assert server._find(unmatched) is None


@pytest.mark.no_clang
@pytest.mark.parametrize(
    "is_pr_event,lines_changed_only,source_files,changed_files",
    [
        (
            True,
            0,
            [FileObj("src/main.cpp")],
            [FileObj("src/main.cpp", [2], [[1, 3]])],
        ),
        (False, 2, [FileObj("src/main.cpp")], []),
    ],
)
def test_main_runs_cli_workflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    is_pr_event: bool,
    lines_changed_only: int,
    source_files: list[FileObj],
    changed_files: list[FileObj],
):
    """Exercise the CLI entrypoint and its sync/async orchestration."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    monkeypatch.chdir(tmp_path)

    args = Args()
    args.repo_root = str(repo_root)
    args.lines_changed_only = lines_changed_only
    args.tidy_review = True
    args.format_review = True

    class FileFilter:
        def parse_submodules(self):
            pass

    class Client:
        def __init__(self):
            self.event_name = "pull_request" if is_pr_event else "push"
            self.client_kind = "github" if is_pr_event else "local"
            self.debug_enabled = False
            self.get_changed_files_args = None
            self.posted = None

        @property
        def is_pr_event(self):
            return is_pr_event

        async def get_changed_files(self, **kwargs):
            self.get_changed_files_args = kwargs
            return changed_files

        async def post_feedback(self, **kwargs):
            self.posted = kwargs

        def start_log_group(self, name: str):
            logger.info("start log group: %s", name)

        def end_log_group(self, name: str):
            logger.info("end log group: %s", name)

    file_filter = FileFilter()
    client = Client()
    monkeypatch.setattr(
        cpp_linter,
        "get_cli_parser",
        lambda: type("Parser", (), {"parse_args": lambda self, **kwargs: args})(),
    )
    monkeypatch.setattr(cpp_linter, "LinterClient", lambda: client)
    monkeypatch.setattr(cpp_linter, "make_file_filter", lambda **kwargs: file_filter)
    monkeypatch.setattr(cpp_linter, "list_source_files", lambda _: source_files)
    monkeypatch.setattr(
        cpp_linter, "capture_clang_tools_output", lambda **kwargs: ClangVersions()
    )
    monkeypatch.setattr(cpp_linter, "CACHE_PATH", tmp_path / "cache")

    cpp_linter.main()

    assert client.get_changed_files_args is not None
    assert client.get_changed_files_args["lines_changed_only"] == (
        0 if is_pr_event else lines_changed_only
    )
    assert client.posted is not None
    assert client.posted["args"] is args
    assert args.files_changed_only is (lines_changed_only > 0)
    assert args.tidy_review is is_pr_event
    assert args.format_review is is_pr_event
    if is_pr_event:
        assert client.posted["files"][0].additions == [2]
        assert client.posted["files"][0].diff_chunks == [[1, 3]]
    else:
        assert "Pull request reviews are only posted" in caplog.text
        assert "No source files need checking!" in caplog.text


@pytest.mark.no_clang
def test_main_version_command(monkeypatch: pytest.MonkeyPatch, capsys):
    """The version command exits before initializing the linter client."""
    args = Args()
    args.command = "version"

    class Parser:
        def parse_args(self, **kwargs):
            return args

    monkeypatch.setattr(cpp_linter, "get_cli_parser", lambda: Parser())

    cpp_linter.main()

    assert capsys.readouterr().out.strip() == cpp_linter.version
