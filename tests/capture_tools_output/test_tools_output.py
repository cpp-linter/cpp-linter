"""Various tests related to the ``lines_changed_only`` option."""
import os
import logging
import shutil
from typing import Dict, Any, cast, List, Optional
from pathlib import Path
import json
import re
import pytest
import cpp_linter
import cpp_linter.run
from cpp_linter.git import parse_diff
from cpp_linter.run import (
    filter_out_non_source_files,
    capture_clang_tools_output,
    make_annotations,
    log_commander,
)
from cpp_linter.thread_comments import list_diff_comments

CLANG_VERSION = os.getenv("CLANG_VERSION", "12")

TEST_REPO_COMMIT_PAIRS: List[Dict[str, str]] = [
    dict(
        repo="chocolate-doom/chocolate-doom",
        commit="67715d6e2725322e6132e9ff99b9a2a3f3b10c83",
    ),
    dict(
        repo="chocolate-doom/chocolate-doom",
        commit="71091562db5b0e7853d08ffa2f110af49cc3bc0d",
    ),
    dict(
        repo="libvips/libvips",
        commit="fe82be345a5b654a76835a7aea5a804bd9ebff0a",
    ),
    dict(
        repo="shenxianpeng/test-repo",
        commit="662ad4cf90084063ea9c089b8de4aff0b8959d0e",
    ),
]


def _translate_lines_changed_only_value(value: int) -> str:
    """generates an id for tests that use lines-changed-only settings."""
    ret_vals = ["all lines", "only added", "only diff"]
    return ret_vals[value]


def flush_prior_artifacts():
    """flush output from any previous tests"""
    cpp_linter.Globals.OUTPUT = ""
    cpp_linter.Globals.FILES.clear()
    cpp_linter.GlobalParser.format_advice.clear()
    cpp_linter.GlobalParser.tidy_advice.clear()
    cpp_linter.GlobalParser.tidy_notes.clear()


def prep_repo(
    monkeypatch: pytest.MonkeyPatch,
    repo: str,
    commit: str,
):
    """Setup a test repo to run the rest of the tests in this module."""
    for name, value in zip(["GITHUB_REPOSITORY", "GITHUB_SHA"], [repo, commit]):
        monkeypatch.setattr(cpp_linter.run, name, value)

    flush_prior_artifacts()
    test_diff = Path(__file__).parent / repo / f"{commit}.diff"
    monkeypatch.setattr(
        cpp_linter.Globals, "FILES", parse_diff(test_diff.read_text(encoding="utf-8"))
    )


def prep_tmp_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    repo: str,
    commit: str,
    copy_configs: bool = False,
    lines_changed_only: int = 0,
):
    """Some extra setup for test's temp directory to ensure needed files exist."""
    monkeypatch.chdir(str(tmp_path))
    prep_repo(
        monkeypatch,
        repo=repo,
        commit=commit,
    )
    if copy_configs:
        for config in ("format", "tidy"):
            shutil.copyfile(
                str(Path(__file__).parent / repo / f".clang-{config}"),
                str(tmp_path / f".clang-{config}"),
            )
    # Make a folder to download the needed files in the tests' temp folder. This is
    # meant to avoid re-downloading the same files for multiple tests run against the
    # same sample repo.
    repo_cache = tmp_path.parent / repo
    repo_cache.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(str(repo_cache))
    filter_out_non_source_files(["c", "h"], [".github"], [], lines_changed_only)
    cpp_linter.run.verify_files_are_present()
    repo_path = tmp_path / repo.split("/")[1]
    shutil.copytree(
        str(repo_cache),
        str(repo_path),
        ignore=shutil.ignore_patterns("\\.changed_files.json"),
    )
    monkeypatch.chdir(repo_path)


@pytest.mark.parametrize(
    "repo_commit_pair",
    [
        (TEST_REPO_COMMIT_PAIRS[0]),
        (TEST_REPO_COMMIT_PAIRS[1]),
        (TEST_REPO_COMMIT_PAIRS[2]),
        (TEST_REPO_COMMIT_PAIRS[3]),
    ],
    ids=["line ranges", "no additions", "large diff", "new file"],
)
@pytest.mark.parametrize(
    "extensions",
    [(["c", "h"]), pytest.param(["hpp"], marks=pytest.mark.xfail)],
    ids=[".c,.h", ".hpp"],
)
@pytest.mark.parametrize(
    "lines_changed_only", [0, 1, 2], ids=_translate_lines_changed_only_value
)
def test_lines_changed_only(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    repo_commit_pair: Dict[str, str],
    extensions: List[str],
    lines_changed_only: int,
):
    """Test for lines changes in diff.

    This checks for
    1. ranges of diff chunks.
    2. ranges of lines in diff that only contain additions.
    """
    caplog.set_level(logging.DEBUG, logger=cpp_linter.logger.name)
    repo, commit = repo_commit_pair["repo"], repo_commit_pair["commit"]
    prep_repo(monkeypatch, repo, commit)
    if filter_out_non_source_files(
        ext_list=extensions,
        ignored=[".github"],
        not_ignored=[],
        lines_changed_only=lines_changed_only,
    ):
        expected_results_json = (
            Path(__file__).parent
            / repo
            / f"expected-result_{commit[:6]}-{lines_changed_only}.json"
        )
        # uncomment to update the expected test's results
        # expected_results_json.write_text(
        #     json.dumps(cpp_linter.Globals.FILES, indent=2) + "\n", encoding="utf-8"
        # )
        test_result = json.loads(expected_results_json.read_text(encoding="utf-8"))
        for file, result in zip(cpp_linter.Globals.FILES, test_result):
            expected = result["line_filter"]["diff_chunks"]
            assert file["line_filter"]["diff_chunks"] == expected
            expected = result["line_filter"]["lines_added"]
            assert file["line_filter"]["lines_added"] == expected
    else:
        raise RuntimeError("test failed to find files")


def match_file_json(filename: str) -> Optional[Dict[str, Any]]:
    """A helper function to match a given filename with a file's JSON object."""
    for file in cpp_linter.Globals.FILES:
        if file["filename"] == filename:
            return file
    print("file", filename, "not found in expected_result.json")
    return None


RECORD_FILE = re.compile(r".*file=(.*?),.*")
FORMAT_RECORD = re.compile(r"Run clang-format on ")
FORMAT_RECORD_LINES = re.compile(r".*\(lines (.*)\).*")
TIDY_RECORD = re.compile(r":\d+:\d+ \[.*\]::")
TIDY_RECORD_LINE = re.compile(r".*,line=(\d+).*")


@pytest.mark.parametrize(
    "lines_changed_only", [0, 1, 2], ids=_translate_lines_changed_only_value
)
@pytest.mark.parametrize("style", ["file", "llvm", "google"])
def test_format_annotations(
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    lines_changed_only: int,
    style: str,
):
    """Test clang-format annotations."""
    prep_tmp_dir(
        tmp_path,
        monkeypatch,
        **TEST_REPO_COMMIT_PAIRS[0],
        copy_configs=True,
        lines_changed_only=lines_changed_only,
    )
    capture_clang_tools_output(
        version=CLANG_VERSION,
        checks="-*",  # disable clang-tidy output
        style=style,
        lines_changed_only=lines_changed_only,
        database="",
        repo_root="",
        extra_args=[],
    )
    assert "Output from `clang-tidy`" not in cpp_linter.Globals.OUTPUT
    caplog.set_level(logging.INFO, logger=log_commander.name)
    log_commander.propagate = True
    make_annotations(
        style=style, file_annotations=True, lines_changed_only=lines_changed_only
    )
    for message in [r.message for r in caplog.records if r.levelno == logging.INFO]:
        if FORMAT_RECORD.search(message) is not None:
            lines = [
                int(l.strip())
                for l in FORMAT_RECORD_LINES.sub("\\1", message).split(",")
            ]
            file = match_file_json(RECORD_FILE.sub("\\1", message).replace("\\", "/"))
            if file is None:
                continue
            ranges = cpp_linter.range_of_changed_lines(file, lines_changed_only)
            if ranges:  # an empty list if lines_changed_only == 0
                for line in lines:
                    assert line in ranges
        else:
            raise RuntimeWarning(f"unrecognized record: {message}")


@pytest.mark.parametrize(
    "lines_changed_only", [0, 1, 2], ids=_translate_lines_changed_only_value
)
@pytest.mark.parametrize(
    "checks",
    [
        "",
        "boost-*,bugprone-*,performance-*,readability-*,portability-*,modernize-*,"
        "clang-analyzer-*,cppcoreguidelines-*",
    ],
    ids=["config file", "action defaults"],
)
def test_tidy_annotations(
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    lines_changed_only: int,
    checks: str,
):
    """Test clang-tidy annotations."""
    prep_tmp_dir(
        tmp_path,
        monkeypatch,
        **TEST_REPO_COMMIT_PAIRS[0],
        copy_configs=False,
        lines_changed_only=lines_changed_only,
    )
    capture_clang_tools_output(
        version=CLANG_VERSION,
        checks=checks,
        style="",  # disable clang-format output
        lines_changed_only=lines_changed_only,
        database="",
        repo_root="",
        extra_args=[],
    )
    assert "Run `clang-format` on the following files" not in cpp_linter.Globals.OUTPUT
    caplog.set_level(logging.INFO, logger=log_commander.name)
    log_commander.propagate = True
    make_annotations(
        style="", file_annotations=True, lines_changed_only=lines_changed_only
    )
    for message in [r.message for r in caplog.records if r.levelno == logging.INFO]:
        if TIDY_RECORD.search(message) is not None:
            line = int(TIDY_RECORD_LINE.sub("\\1", message))
            file = match_file_json(RECORD_FILE.sub("\\1", message).replace("\\", "/"))
            if file is None:
                continue
            ranges = cpp_linter.range_of_changed_lines(file, lines_changed_only)
            if ranges:  # an empty list if lines_changed_only == 0
                assert line in ranges
        else:
            raise RuntimeWarning(f"unrecognized record: {message}")


@pytest.mark.parametrize(
    "repo_commit_pair",
    [
        (TEST_REPO_COMMIT_PAIRS[0]),
        (TEST_REPO_COMMIT_PAIRS[1]),
        (TEST_REPO_COMMIT_PAIRS[3]),
    ],
    ids=["line ranges", "no additions", "new file"],
)
@pytest.mark.parametrize(
    "lines_changed_only", [1, 2], ids=_translate_lines_changed_only_value
)
def test_diff_comment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    repo_commit_pair: Dict[str, str],
    lines_changed_only: int,
):
    """Tests code that isn't actually used (yet) for posting
    comments (not annotations) in the event's diff.

    Remember, diff comments should only focus on lines in the diff."""
    prep_tmp_dir(
        tmp_path,
        monkeypatch,
        **repo_commit_pair,
        copy_configs=True,
        lines_changed_only=lines_changed_only,
    )
    capture_clang_tools_output(
        version=CLANG_VERSION,
        checks="",
        style="file",
        lines_changed_only=lines_changed_only,
        database="",
        repo_root="",
        extra_args=[],
    )
    diff_comments = list_diff_comments(lines_changed_only)
    # output = Path(__file__).parent / "diff_comments.json"
    # output.write_text(json.dumps(diff_comments, indent=2), encoding="utf-8")
    for comment in diff_comments:
        file = match_file_json(cast(str, comment["path"]))
        if file is None:
            continue
        ranges = cpp_linter.range_of_changed_lines(file, lines_changed_only)
        assert comment["line"] in ranges
