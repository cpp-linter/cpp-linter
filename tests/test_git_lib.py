from pathlib import Path
from typing import List, cast

import pytest
import pygit2  # type: ignore[import-not-found]

from cpp_linter import FileObj, Globals, CACHE_PATH
from cpp_linter.run import filter_out_non_source_files
from cpp_linter.git_lib import get_diff, parse_diff


@pytest.mark.parametrize(
    "sha",
    [
        "950ff0b690e1903797c303c5fc8d9f3b52f1d3c5",  # has modded C++ sources
        "0c236809891000b16952576dc34de082d7a40bf3",  # has no modded C++ sources
    ],
    ids=["modded-src", "no-modded-src"],
)
def test_parse_diff(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sha: str):
    """Use a git clone to test run parse_diff()."""
    monkeypatch.chdir(str(tmp_path))
    repo = pygit2.clone_repository("https://github.com/cpp-linter/cpp-linter", ".")
    commit = repo.revparse_single(sha)
    repo.checkout_tree(
        cast(pygit2.Commit, commit).tree,
        # reset index to specified commit
        strategy=pygit2.GIT_CHECKOUT_FORCE | pygit2.GIT_CHECKOUT_RECREATE_MISSING,
    )
    repo.set_head(commit.oid)  # detach head
    del repo
    Path(CACHE_PATH).mkdir()
    files: List[FileObj] = parse_diff(get_diff())
    assert files
    monkeypatch.setattr(Globals, "FILES", files)
    filter_out_non_source_files(["cpp", "hpp"], [], [], 0)
    if sha == "950ff0b690e1903797c303c5fc8d9f3b52f1d3c5":
        assert Globals.FILES
    else:
        assert not Globals.FILES
