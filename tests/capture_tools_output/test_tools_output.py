"""Various tests related to the ``lines_changed_only`` option."""
import json
import logging
import os
from pathlib import Path
import urllib.parse
import re
import shutil
from typing import Dict, cast, List, Optional
import warnings

import pygit2  # type: ignore
import pytest
import requests_mock

from cpp_linter.common_fs import FileObj, CACHE_PATH
from cpp_linter.git import parse_diff, get_diff
from cpp_linter.clang_tools import capture_clang_tools_output
from cpp_linter.loggers import log_commander, logger
from cpp_linter.rest_api.github_api import GithubApiClient
from cpp_linter.cli import cli_arg_parser

CLANG_VERSION = os.getenv("CLANG_VERSION", "16")

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


def prep_api_client(
    monkeypatch: pytest.MonkeyPatch,
    repo: str,
    commit: str,
) -> GithubApiClient:
    """Setup a test repo to run the rest of the tests in this module."""
    for name, value in zip(["GITHUB_REPOSITORY", "GITHUB_SHA"], [repo, commit]):
        monkeypatch.setenv(name, value)
    gh_client = GithubApiClient()
    gh_client.repo = repo
    gh_client.sha = commit

    # prevent CI tests in PRs from altering the URL used in the mock tests
    monkeypatch.setenv("CI", "true")  # make fake requests using session adaptor
    gh_client.event_payload.clear()
    gh_client.event_name = "push"

    adapter = requests_mock.Adapter(case_sensitive=True)

    test_backup = Path(__file__).parent / repo / commit

    # setup responses for getting diff
    test_diff = test_backup / "patch.diff"
    diff = ""
    if test_diff.exists():
        diff = test_diff.read_text(encoding="utf-8")
    adapter.register_uri("GET", f"/repos/{repo}/commits/{commit}", text=diff)

    # set responses for "downloading" file backups from
    # tests/capture_tools_output/{repo}/{commit}/cache
    cache_path = test_backup / "cache"
    for file in cache_path.rglob("*.*"):
        adapter.register_uri(
            "GET",
            f"/{repo}/raw/{commit}/" + urllib.parse.quote(file.as_posix(), safe=""),
            text=file.read_text(encoding="utf-8"),
        )

    mock_protocol = "http+mock://"
    gh_client.api_url = gh_client.api_url.replace("https://", mock_protocol)
    gh_client.session.mount(mock_protocol, adapter)
    return gh_client


def prep_tmp_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    repo: str,
    commit: str,
    lines_changed_only: int,
    copy_configs: bool = False,
):
    """Some extra setup for test's temp directory to ensure needed files exist."""
    monkeypatch.chdir(str(tmp_path))
    gh_client = prep_api_client(
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
    CACHE_PATH.mkdir(exist_ok=True)
    files = gh_client.get_list_of_changed_files(
        extensions=["c", "h", "hpp", "cpp"],
        ignored=[".github"],
        not_ignored=[],
        lines_changed_only=lines_changed_only,
    )
    gh_client.verify_files_are_present(files)
    repo_path = tmp_path / repo.split("/")[1]
    shutil.copytree(
        str(repo_cache),
        str(repo_path),
        ignore=shutil.ignore_patterns(f"{CACHE_PATH}/**"),
    )
    monkeypatch.chdir(repo_path)

    return (gh_client, files)


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
    caplog.set_level(logging.DEBUG, logger=logger.name)
    repo, commit = repo_commit_pair["repo"], repo_commit_pair["commit"]
    CACHE_PATH.mkdir(exist_ok=True)
    gh_client = prep_api_client(monkeypatch, repo, commit)
    files = gh_client.get_list_of_changed_files(
        extensions=extensions,
        ignored=[".github"],
        not_ignored=[],
        lines_changed_only=lines_changed_only,
    )
    if files:
        expected_results_json = (
            Path(__file__).parent
            / repo
            / commit
            / f"expected-result_{lines_changed_only}.json"
        )
        ### uncomment this paragraph to update/generate the expected test's results
        # expected_results_json.write_text(
        #     json.dumps([f.serialize() for f in files], indent=2) + "\n",
        #     encoding="utf-8",
        # )
        test_result = json.loads(expected_results_json.read_text(encoding="utf-8"))
        for file_obj, result in zip(files, test_result):
            assert file_obj.name == result["filename"]
            expected = result["line_filter"]["diff_chunks"]
            assert file_obj.diff_chunks == expected
            expected = result["line_filter"]["lines_added"]
            assert file_obj.lines_added == expected
    else:
        raise RuntimeError("test failed to find files")


def match_file_json(filename: str, files: List[FileObj]) -> Optional[FileObj]:
    """A helper function to match a given filename with a file object's name."""
    for file_obj in files:
        if file_obj.name == filename:
            return file_obj
    print("file", filename, "not found in expected_result.json")  # pragma: no cover
    return None  # pragma: no cover


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
    gh_client, files = prep_tmp_dir(
        tmp_path,
        monkeypatch,
        **TEST_REPO_COMMIT_PAIRS[0],
        lines_changed_only=lines_changed_only,
        copy_configs=True,
    )
    format_advice, tidy_advice = capture_clang_tools_output(
        files,
        version=CLANG_VERSION,
        checks="-*",  # disable clang-tidy output
        style=style,
        lines_changed_only=lines_changed_only,
        database="",
        extra_args=[],
        tidy_review=False,
        format_review=False,
    )
    assert [note for note in format_advice]
    assert not [note for concern in tidy_advice for note in concern.notes]

    caplog.set_level(logging.INFO, logger=log_commander.name)
    log_commander.propagate = True

    # check thread comment
    comment, format_checks_failed, _ = gh_client.make_comment(
        files, format_advice, tidy_advice
    )
    if format_checks_failed:
        assert f"{format_checks_failed} file(s) not formatted</strong>" in comment

    # check annotations
    gh_client.make_annotations(files, format_advice, tidy_advice, style)
    for message in [r.message for r in caplog.records if r.levelno == logging.INFO]:
        if FORMAT_RECORD.search(message) is not None:
            line_list = message[message.find("style guidelines. (lines ") + 25 : -1]
            lines = [int(line.strip()) for line in line_list.split(",")]
            file_obj = match_file_json(
                RECORD_FILE.sub("\\1", message).replace("\\", "/"), files
            )
            if file_obj is None:
                continue  # pragma: no cover
            if lines_changed_only == 0:
                continue
            ranges = cast(
                List[List[int]],
                file_obj.range_of_changed_lines(lines_changed_only, get_ranges=True),
            )
            for line in lines:
                for r in ranges:  # an empty list if lines_changed_only == 0
                    if line in range(r[0], r[1]):
                        break
                else:  # pragma: no cover
                    raise RuntimeError(f"line {line} not in ranges {repr(ranges)}")
        else:  # pragma: no cover
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
    gh_client, files = prep_tmp_dir(
        tmp_path,
        monkeypatch,
        **TEST_REPO_COMMIT_PAIRS[4],
        lines_changed_only=lines_changed_only,
        copy_configs=False,
    )
    format_advice, tidy_advice = capture_clang_tools_output(
        files,
        version=CLANG_VERSION,
        checks=checks,
        style="",  # disable clang-format output
        lines_changed_only=lines_changed_only,
        database="",
        extra_args=[],
        tidy_review=False,
        format_review=False,
    )
    assert [note for concern in tidy_advice for note in concern.notes]
    assert not [note for note in format_advice]
    caplog.set_level(logging.DEBUG)
    log_commander.propagate = True
    gh_client.make_annotations(files, format_advice, tidy_advice, style="")
    _, format_checks_failed, tidy_checks_failed = gh_client.make_comment(
        files, format_advice, tidy_advice
    )
    assert not format_checks_failed
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
            file_obj = match_file_json(filename, files)
            checks_failed += 1
            if file_obj is None:  # pragma: no cover
                warnings.warn(
                    RuntimeWarning(f"{filename} was not matched with project src")
                )
                continue
            ranges = file_obj.range_of_changed_lines(lines_changed_only)
            if ranges:  # an empty list if lines_changed_only == 0
                assert line in ranges
        else:  # pragma: no cover
            raise RuntimeWarning(f"unrecognized record: {message}")
    assert tidy_checks_failed == checks_failed


def test_all_ok_comment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify the comment is affirmative when no attention is needed."""
    monkeypatch.chdir(str(tmp_path))

    files: List[FileObj] = []  # no files to test means no concerns to note

    # this call essentially does nothing with the file system
    format_advice, tidy_advice = capture_clang_tools_output(
        files,
        version=CLANG_VERSION,
        checks="-*",
        style="",
        lines_changed_only=0,
        database="",
        extra_args=[],
        tidy_review=False,
        format_review=False,
    )
    comment, format_checks_failed, tidy_checks_failed = GithubApiClient.make_comment(
        files, format_advice, tidy_advice
    )
    assert "No problems need attention." in comment
    assert not format_checks_failed
    assert not tidy_checks_failed


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

    Path(CACHE_PATH).mkdir()
    files = parse_diff(
        get_diff(),
        extensions=["cpp", "hpp"],
        ignored=[],
        not_ignored=[],
        lines_changed_only=0,
    )
    if sha == TEST_REPO_COMMIT_PAIRS[4]["commit"] or patch:
        assert files
    else:
        assert not files


@pytest.mark.parametrize(
    "user_input",
    [["-std=c++17", "-Wall"], ["-std=c++17 -Wall"]],
    ids=["separate", "unified"],
)
def test_tidy_extra_args(caplog: pytest.LogCaptureFixture, user_input: List[str]):
    """Just make sure --extra-arg is passed to clang-tidy properly"""
    cli_in = []
    for a in user_input:
        cli_in.append(f'--extra-arg="{a}"')
    caplog.set_level(logging.INFO, logger=logger.name)
    args = cli_arg_parser.parse_args(cli_in)
    assert len(user_input) == len(args.extra_arg)
    _, _ = capture_clang_tools_output(
        files=[FileObj("tests/demo/demo.cpp")],
        version=CLANG_VERSION,
        checks="",  # use .clang-tidy config
        style="",  # disable clang-format
        lines_changed_only=0,
        database="",
        extra_args=args.extra_arg,
        tidy_review=False,
        format_review=False,
    )
    messages = [
        r.message
        for r in caplog.records
        if r.levelno == logging.INFO and r.message.startswith("Running")
    ]
    assert messages
    if len(user_input) == 1 and " " in user_input[0]:
        user_input = user_input[0].split()
    for a in user_input:
        assert f'--extra-arg="{a}"' in messages[0]
