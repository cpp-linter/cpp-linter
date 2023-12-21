"""Tests specific to specifying the compilation database path."""
from typing import List
from pathlib import Path, PurePath
import logging
import os
import re
import pytest
from cpp_linter import logger, FileObj
import cpp_linter.run
import cpp_linter
from cpp_linter.run import capture_clang_tools_output

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
    pytestconfig: pytest.Config,
    database: str,
    expected_args: List[str],
):
    """test clang-tidy using a implicit path to the compilation database."""
    monkeypatch.chdir(PurePath(__file__).parent.as_posix())
    cpp_linter.CACHE_PATH.mkdir(exist_ok=True)
    demo_src = "../demo/demo.cpp"
    monkeypatch.setattr(
        cpp_linter.run,
        "RUNNER_WORKSPACE",
        Path(pytestconfig.rootpath, "tests").resolve().as_posix(),
    )
    monkeypatch.setattr(cpp_linter.Globals, "FILES", [FileObj(demo_src, [], [])])

    caplog.set_level(logging.DEBUG, logger=logger.name)
    capture_clang_tools_output(
        version=os.getenv("CLANG_VERSION", "12"),
        checks="",  # let clang-tidy use a .clang-tidy config file
        style="",  # don't invoke clang-format
        lines_changed_only=0,  # analyze complete file
        database=database,
        repo_root=".",
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
