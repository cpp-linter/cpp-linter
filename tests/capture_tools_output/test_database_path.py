"""Tests specific to specifying the compilation database path."""

from typing import List
from pathlib import Path, PurePath
import logging
import os
import re
import shutil
import subprocess
import pytest
from cpp_linter.loggers import logger
from cpp_linter.common_fs import FileObj, CACHE_PATH
from cpp_linter.rest_api.github_api import GithubApiClient
from cpp_linter.clang_tools import ClangVersions, capture_clang_tools_output
from cpp_linter.clang_tools.clang_format import tally_format_advice
from cpp_linter.clang_tools.clang_tidy import tally_tidy_advice
from cpp_linter.cli import Args

DEFAULT_CLANG_VERSION = "16"
CLANG_VERSION = os.getenv("CLANG_VERSION", DEFAULT_CLANG_VERSION)
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
    capsys: pytest.CaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    database: str,
    expected_args: List[str],
):
    """test clang-tidy using a implicit path to the compilation database."""
    monkeypatch.setenv("COVERAGE_FILE", str(Path.cwd() / ".coverage"))
    monkeypatch.chdir(PurePath(__file__).parent.parent.as_posix())
    monkeypatch.setenv("CPP_LINTER_PYTEST_NO_RICH", "1")
    CACHE_PATH.mkdir(exist_ok=True)
    logger.setLevel(logging.DEBUG)
    demo_src = "demo/demo.cpp"
    files = [FileObj(demo_src)]

    args = Args()
    args.database = database
    args.tidy_checks = ""  # let clang-tidy use a .clang-tidy config file
    args.version = CLANG_VERSION
    args.style = ""  # don't invoke clang-format
    args.extensions = ["cpp", "hpp"]
    args.lines_changed_only = 0  # analyze complete file

    capture_clang_tools_output(files, args=args)
    stdout = capsys.readouterr().out
    assert "Error while trying to load a compilation database" not in stdout
    msg_match = CLANG_TIDY_COMMAND.search(stdout)
    if msg_match is None:  # pragma: no cover
        pytest.fail("failed to find args passed in clang-tidy in log records")
    matched_args = msg_match.group(0).split()[1:]
    expected_args.append(demo_src.replace("/", os.sep) + '"')
    assert expected_args == matched_args


def test_ninja_database(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
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
    monkeypatch.setenv("COVERAGE_FILE", str(Path.cwd() / ".coverage"))
    monkeypatch.chdir(str(tmp_path_demo))
    subprocess.run(["meson", "init"])
    subprocess.run(["meson", "setup", "--backend=ninja", "build", "."])
    monkeypatch.setenv("CPP_LINTER_PYTEST_NO_RICH", "1")

    logger.setLevel(logging.DEBUG)
    files = [FileObj("demo.cpp")]

    args = Args()
    args.database = "build"  # point to generated compile_commands.txt
    args.tidy_checks = ""  # let clang-tidy use a .clang-tidy config file
    args.version = CLANG_VERSION
    args.style = ""  # don't invoke clang-format
    args.extensions = ["cpp", "hpp"]
    args.lines_changed_only = 0  # analyze complete file

    # run clang-tidy and verify paths of project files were matched with database paths
    clang_versions: ClangVersions = capture_clang_tools_output(files, args=args)
    found_project_file = False
    for concern in [a.tidy_advice for a in files if a.tidy_advice]:
        for note in concern.notes:
            if note.filename.endswith("demo.cpp") or note.filename.endswith("demo.hpp"):
                assert not Path(note.filename).is_absolute()
                found_project_file = True
    if not found_project_file:  # pragma: no cover
        pytest.fail("no project files raised concerns with clang-tidy")

    format_checks_failed = tally_format_advice(files)
    tidy_checks_failed = tally_tidy_advice(files)
    comment = GithubApiClient.make_comment(
        files=files,
        tidy_checks_failed=tidy_checks_failed,
        format_checks_failed=format_checks_failed,
        clang_versions=clang_versions,
    )

    assert tidy_checks_failed
    assert not format_checks_failed

    # write step-summary for manual verification
    Path(tmp_path, "job_summary.md").write_text(comment, encoding="utf-8")
