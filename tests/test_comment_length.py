from pathlib import Path
import pytest
from cpp_linter.rest_api.github_api import GithubApiClient
from cpp_linter.rest_api import USER_OUTREACH
from cpp_linter.clang_tools.clang_format import FormatAdvice, FormatReplacementLine
from cpp_linter.common_fs import FileObj
from cpp_linter.clang_tools import ClangVersions


@pytest.mark.no_clang
def test_comment_length_limit(tmp_path: Path):
    """Ensure comment length does not exceed specified limit for thread-comments but is
    unhindered for step-summary"""
    file_name = "tests/demo/demo.cpp"
    abs_limit = 65535
    format_checks_failed = 3000
    file = FileObj(file_name)
    dummy_advice = FormatAdvice(file_name)
    dummy_advice.replaced_lines = [FormatReplacementLine(line_numb=1)]
    file.format_advice = dummy_advice
    clang_versions = ClangVersions()
    clang_versions.format = "x.y.z"
    files = [file] * format_checks_failed
    thread_comment = GithubApiClient.make_comment(
        files=files,
        format_checks_failed=format_checks_failed,
        tidy_checks_failed=0,
        clang_versions=clang_versions,
        len_limit=abs_limit,
    )
    assert len(thread_comment) < abs_limit
    assert thread_comment.endswith(USER_OUTREACH)
    step_summary = GithubApiClient.make_comment(
        files=files,
        format_checks_failed=format_checks_failed,
        tidy_checks_failed=0,
        clang_versions=clang_versions,
        len_limit=None,
    )
    assert len(step_summary) != len(thread_comment)
    assert step_summary.endswith(USER_OUTREACH)

    # output each in test dir for visual inspection
    # use open() because Path.write_text() added `new_line` param in python v3.10
    with open(
        str(tmp_path / "thread_comment.md"), mode="w", encoding="utf-8", newline="\n"
    ) as f_out:
        f_out.write(thread_comment)
    with open(
        str(tmp_path / "step_summary.md"), mode="w", encoding="utf-8", newline="\n"
    ) as f_out:
        f_out.write(step_summary)
