from pathlib import Path
from typing import List, cast

import pytest
import pygit2  # type: ignore[import-not-found]

from cpp_linter import FileObj, Globals, CACHE_PATH
from cpp_linter.run import filter_out_non_source_files
from cpp_linter.git_lib import get_diff, parse_diff

# SHA of commits on this repo's main branch
MODDED_C_SRC_SHA = "950ff0b690e1903797c303c5fc8d9f3b52f1d3c5"
NO_MODDED_C_SRC_SHA = "0c236809891000b16952576dc34de082d7a40bf3"

# This patch needs to have trailing whitespaces to signify unmodified lines
PATCH_TO_STAGE = (Path(__file__).parent / "git_lib.patch").read_text(encoding="utf-8")
# WARNING, this patch deletes the file tests/demo/.clang-format
# DO NOT APPLY THIS PATCH TO THIS REPO!
# It is meant to be applied to a temporary git clone (isolated test copy of this repo).

@pytest.mark.parametrize(
    "sha,patch",
    [
        (MODDED_C_SRC_SHA, ""),  # has modded C++ sources
        (NO_MODDED_C_SRC_SHA, ""),  # has no modded C++ sources
        (MODDED_C_SRC_SHA, PATCH_TO_STAGE),  # has modded C++ sources staged to commit
    ],
    ids=["modded-src", "no-modded-src", "staged-modded-src"],
)
def test_parse_diff(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sha: str, patch: str
):
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
    if patch:
        diff = repo.diff()
        diff = diff.parse_diff(patch)
        repo.apply(diff, pygit2.GIT_APPLY_LOCATION_BOTH)
        repo.index.add_all(["tests/demo/demo.*"])
        repo.index.write()
    del repo
    Path(CACHE_PATH).mkdir()
    files: List[FileObj] = parse_diff(get_diff())
    assert files
    monkeypatch.setattr(Globals, "FILES", files)
    filter_out_non_source_files(["cpp", "hpp"], [], [], 0)
    if sha == MODDED_C_SRC_SHA or patch:
        assert Globals.FILES
    else:
        assert not Globals.FILES
