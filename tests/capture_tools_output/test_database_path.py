"""Tests specific to specifying the compilation database path."""
from typing import List
from pathlib import Path, PurePath
import logging
import os
import re
import sys
import shutil
import pytest
from cpp_linter.loggers import logger
from cpp_linter.common_fs import FileObj, CACHE_PATH
from cpp_linter.rest_api.github_api import GithubApiClient
from cpp_linter.clang_tools import capture_clang_tools_output
from mesonbuild.mesonmain import main as meson  # type: ignore[import-untyped]

CLANG_TIDY_COMMAND = re.compile(r'clang-tidy[^\s]*\s(.*)"')

ABS_DB_PATH = str(Path("tests/demo").resolve())


@pytest.mark.parametrize(
    "database,expected_args",
    [
        # implicit path to the compilation database
        ("", []),
        # explicit relative path to the compilation database
        ("demo", ["-p", ABS_DB_PATH]),
        # explicit absolute path to the compilation database
        (ABS_DB_PATH, ["-p", ABS_DB_PATH]),
    ],
    ids=["implicit path", "relative path", "absolute path"],
)
def test_db_detection(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    database: str,
    expected_args: List[str],
):
    """test clang-tidy using a implicit path to the compilation database."""
    monkeypatch.chdir(PurePath(__file__).parent.parent.as_posix())
    CACHE_PATH.mkdir(exist_ok=True)
    caplog.set_level(logging.DEBUG, logger=logger.name)
    demo_src = "../demo/demo.cpp"
    files = [FileObj(demo_src, [], [])]

    _ = capture_clang_tools_output(
        files,
        version=os.getenv("CLANG_VERSION", "12"),
        checks="",  # let clang-tidy use a .clang-tidy config file
        style="",  # don't invoke clang-format
        lines_changed_only=0,  # analyze complete file
        database=database,
        extra_args=[],
    )
    matched_args = []
    for record in caplog.records:
        assert "Error while trying to load a compilation database" not in record.message
        msg_match = CLANG_TIDY_COMMAND.search(record.message)
        if msg_match is not None:
            matched_args = msg_match.group(0).split()[1:]
            break
    else:
        raise RuntimeError("failed to find args passed in clang-tidy in log records")
    expected_args.append(demo_src.replace("/", os.sep) + '"')
    assert expected_args == matched_args


def test_ninja_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    """verify that the relative paths used in a database generated (and thus clang-tidy
    stdout) for the ninja build system are resolved accordingly."""
    tmp_path_demo = tmp_path / "demo"
    # generate the project
    shutil.copytree(
        str(Path(__file__).parent.parent / "demo"),
        str(tmp_path_demo),
        ignore=shutil.ignore_patterns("compile_flags.txt"),
    )
    (tmp_path_demo / "build").mkdir(parents=True)
    monkeypatch.chdir(str(tmp_path_demo))
    monkeypatch.setattr(sys, "argv", ["meson", "init"])
    meson()
    monkeypatch.setattr(
        sys, "argv", ["meson", "setup", "--backend=ninja", "build", "."]
    )
    meson()

    caplog.set_level(logging.DEBUG, logger=logger.name)
    files = [FileObj("demo.cpp", [], [])]
    gh_client = GithubApiClient()

    # run clang-tidy and verify paths of project files were matched with database paths
    (format_advice, tidy_advice) = capture_clang_tools_output(
        files,
        version=os.getenv("CLANG_VERSION", "12"),
        checks="",  # let clang-tidy use a .clang-tidy config file
        style="",  # don't invoke clang-format
        lines_changed_only=0,  # analyze complete file
        database="build",  # point to generated compile_commands.txt
        extra_args=[],
    )
    found_project_file = False
    for notes in tidy_advice:
        for note in notes:
            if note.filename.endswith("demo.cpp") or note.filename.endswith("demo.hpp"):
                assert not Path(note.filename).is_absolute()
                found_project_file = True
    if not found_project_file:
        raise RuntimeError("no project files raised concerns with clang-tidy")
    (comment, format_checks_failed, tidy_checks_failed) = gh_client.make_comment(
        files, format_advice, tidy_advice
    )
    assert tidy_checks_failed
    assert not format_checks_failed

    # write step-summary for manual verification
    Path(tmp_path, "job_summary.md").write_text(comment, encoding="utf-8")
