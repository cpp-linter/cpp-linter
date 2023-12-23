"""Various tests related to the ``lines_changed_only`` option."""
import os
import logging
import shutil
from typing import Dict, cast, List, Optional
from pathlib import Path
import json
import re
import warnings
import pygit2  # type: ignore[import-not-found]
import pytest
import cpp_linter
import cpp_linter.run
from cpp_linter.git import parse_diff, get_diff
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
    dict(
        repo="cpp-linter/cpp-linter",
        commit="950ff0b690e1903797c303c5fc8d9f3b52f1d3c5",
    ),
    dict(
        repo="cpp-linter/cpp-linter",
        commit="0c236809891000b16952576dc34de082d7a40bf3",  # no modded C++ sources
    ),
]


def _translate_lines_changed_only_value(value: int) -> str:
    """generates an id for tests that use lines-changed-only settings."""
    ret_vals = ["all lines", "only added", "only diff"]
    return ret_vals[value]


def flush_prior_artifacts(monkeypatch: pytest.MonkeyPatch):
    """flush output from any previous tests"""
    monkeypatch.setattr(cpp_linter.Globals, "OUTPUT", "")
    monkeypatch.setattr(cpp_linter.Globals, "TIDY_COMMENT", "")
    monkeypatch.setattr(cpp_linter.Globals, "FORMAT_COMMENT", "")
    monkeypatch.setattr(cpp_linter.Globals, "FILES", [])
    monkeypatch.setattr(cpp_linter.Globals, "format_failed_count", 0)
    monkeypatch.setattr(cpp_linter.Globals, "tidy_failed_count", 0)
    monkeypatch.setattr(cpp_linter.GlobalParser, "format_advice", [])
    monkeypatch.setattr(cpp_linter.GlobalParser, "tidy_advice", [])
    monkeypatch.setattr(cpp_linter.GlobalParser, "tidy_notes", [])


def prep_repo(
    monkeypatch: pytest.MonkeyPatch,
    repo: str,
    commit: str,
):
    """Setup a test repo to run the rest of the tests in this module."""
    for name, value in zip(["GITHUB_REPOSITORY", "GITHUB_SHA"], [repo, commit]):
        monkeypatch.setattr(cpp_linter.run, name, value)

    flush_prior_artifacts(monkeypatch)
    test_diff = Path(__file__).parent / repo / f"{commit}.diff"
    if test_diff.exists():
        monkeypatch.setattr(
            cpp_linter.Globals,
            "FILES",
            parse_diff(test_diff.read_text(encoding="utf-8")),
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
    repo_cache = tmp_path.parent / repo / commit
    repo_cache.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(str(repo_cache))
    cpp_linter.CACHE_PATH.mkdir(exist_ok=True)
    filter_out_non_source_files(
        ["c", "h", "hpp", "cpp"], [".github"], [], lines_changed_only
    )
    cpp_linter.run.verify_files_are_present()
    repo_path = tmp_path / repo.split("/")[1]
    shutil.copytree(
        str(repo_cache),
        str(repo_path),
        ignore=shutil.ignore_patterns(f"{cpp_linter.CACHE_PATH}/**"),
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
    cpp_linter.CACHE_PATH.mkdir(exist_ok=True)
    filter_out_non_source_files(
        ext_list=extensions,
        ignored=[".github"],
        not_ignored=[],
        lines_changed_only=lines_changed_only,
    )
    if cpp_linter.Globals.FILES:
        expected_results_json = (
            Path(__file__).parent
            / repo
            / f"expected-result_{commit[:6]}-{lines_changed_only}.json"
        )
        ### uncomment this paragraph to update/generate the expected test's results
        # expected_results_json.write_text(
        #     json.dumps([f.serialize() for f in cpp_linter.Globals.FILES], indent=2)
        #     + "\n",
        #     encoding="utf-8",
        # )
        test_result = json.loads(expected_results_json.read_text(encoding="utf-8"))
        for file_obj, result in zip(cpp_linter.Globals.FILES, test_result):
            expected = result["line_filter"]["diff_chunks"]
            assert file_obj.diff_chunks == expected
            expected = result["line_filter"]["lines_added"]
            assert file_obj.lines_added == expected
    else:
        raise RuntimeError("test failed to find files")


def match_file_json(filename: str) -> Optional[cpp_linter.FileObj]:
    """A helper function to match a given filename with a file's JSON object."""
    for file_obj in cpp_linter.Globals.FILES:
        if file_obj.name == filename:
            return file_obj
    print("file", filename, "not found in expected_result.json")
    return None


RECORD_FILE = re.compile(r"^::\w+\sfile=([\/\w\-\\\.\s]+),.*$")
FORMAT_RECORD = re.compile(r"Run clang-format on ")
TIDY_RECORD = re.compile(r":\d+:\d+ \[.*\]::")
TIDY_RECORD_LINE = re.compile(r"^::\w+\sfile=[\/\w\-\\\.\s]+,line=(\d+),.*$")


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
            line_list = message[message.find("style guidelines. (lines ") + 25 : -1]
            lines = [int(line.strip()) for line in line_list.split(",")]
            file_obj = match_file_json(
                RECORD_FILE.sub("\\1", message).replace("\\", "/")
            )
            if file_obj is None:
                continue
            ranges = file_obj.range_of_changed_lines(lines_changed_only)
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
        **TEST_REPO_COMMIT_PAIRS[4],
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
    caplog.set_level(logging.DEBUG)
    log_commander.propagate = True
    make_annotations(
        style="", file_annotations=True, lines_changed_only=lines_changed_only
    )
    messages = [
        r.message
        for r in caplog.records
        if r.levelno == logging.INFO and r.name == log_commander.name
    ]
    assert messages
    checks_failed = 0
    for message in messages:
        if TIDY_RECORD.search(message) is not None:
            line = int(TIDY_RECORD_LINE.sub("\\1", message))
            filename = RECORD_FILE.sub("\\1", message).replace("\\", "/")
            file_obj = match_file_json(filename)
            checks_failed += 1
            if file_obj is None:
                warnings.warn(
                    RuntimeWarning(f"{filename} was not matched with project src")
                )
                continue
            ranges = file_obj.range_of_changed_lines(lines_changed_only)
            if ranges:  # an empty list if lines_changed_only == 0
                assert line in ranges
        else:
            raise RuntimeWarning(f"unrecognized record: {message}")
    output = [
        r.message for r in caplog.records if r.message.endswith(" checks-failed")
    ][0]
    assert output
    assert int(output.split(" ", maxsplit=1)[0]) == checks_failed


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
    monkeypatch.setenv("CPP_LINTER_TEST_ALPHA_CODE", "true")
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
    # the following can be used to manually inspect test results (if needed)
    # #output = Path(__file__).parent / "diff_comments.json"
    # #output.write_text(json.dumps(diff_comments, indent=2), encoding="utf-8")
    for comment in diff_comments:
        file_obj = match_file_json(cast(str, comment["path"]))
        if file_obj is None:
            continue
        ranges = file_obj.range_of_changed_lines(lines_changed_only)
        assert comment["line"] in ranges


def test_all_ok_comment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify the comment is affirmative when no attention is needed."""
    monkeypatch.chdir(str(tmp_path))
    flush_prior_artifacts(monkeypatch)

    # this call essentially does nothing with the file system
    capture_clang_tools_output(
        version=CLANG_VERSION,
        checks="-*",
        style="",
        lines_changed_only=0,
        database="",
        repo_root="",
        extra_args=[],
    )
    assert "No problems need attention." in cpp_linter.Globals.OUTPUT


@pytest.mark.parametrize(
    "repo_commit_pair,patch",
    [
        (TEST_REPO_COMMIT_PAIRS[4], ""),  # has modded C++ sources
        (TEST_REPO_COMMIT_PAIRS[5], ""),  # has no modded C++ sources
        (TEST_REPO_COMMIT_PAIRS[5], "test_git_lib.patch"),
    ],
    ids=["modded-src", "no-modded-src", "staged-modded-src"],
)
def test_parse_diff(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    repo_commit_pair: Dict[str, str],
    patch: str,
):
    """Use a git clone to test run parse_diff()."""
    prep_repo(monkeypatch, **repo_commit_pair)
    repo_name, sha = repo_commit_pair["repo"], repo_commit_pair["commit"]
    repo_cache = tmp_path.parent / repo_name / "HEAD"
    repo_cache.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(str(repo_cache))
    if not (repo_cache / ".git").exists():
        pygit2.clone_repository(f"https://github.com/{repo_name}", ".")
    repo_path = tmp_path / repo_name.split("/")[1]
    shutil.copytree(str(repo_cache), str(repo_path))
    monkeypatch.chdir(repo_path)

    repo = pygit2.Repository(".")
    commit = repo.revparse_single(sha)
    repo.checkout_tree(
        cast(pygit2.Commit, commit).tree,
        # reset index to specified commit
        strategy=pygit2.GIT_CHECKOUT_FORCE | pygit2.GIT_CHECKOUT_RECREATE_MISSING,
    )
    repo.set_head(commit.oid)  # detach head
    if patch:
        diff = repo.diff()
        patch_to_stage = (Path(__file__).parent / repo_name / patch).read_text(
            encoding="utf-8"
        )
        diff = diff.parse_diff(patch_to_stage)
        repo.apply(diff, pygit2.GIT_APPLY_LOCATION_BOTH)
        repo.index.add_all(["tests/demo/demo.*"])
        repo.index.write()
    del repo

    Path(cpp_linter.CACHE_PATH).mkdir()
    files: List[cpp_linter.FileObj] = parse_diff(get_diff())
    assert files
    monkeypatch.setattr(cpp_linter.Globals, "FILES", files)
    filter_out_non_source_files(["cpp", "hpp"], [], [], 0)
    if sha == TEST_REPO_COMMIT_PAIRS[4]["commit"] or patch:
        assert cpp_linter.Globals.FILES
    else:
        assert not cpp_linter.Globals.FILES
