TYPICAL_DIFF = "\n".join(
    [
        "diff --git a/path/for/Some file.cpp b/path/to/Some file.cpp",
        "--- a/path/for/Some file.cpp",
        "+++ b/path/to/Some file.cpp",
        "@@ -3,7 +3,7 @@",
        " ",
        " ",
        " ",
        "-#include <some_lib/render/animation.hpp>",
        "+#include <some_lib/render/animations.hpp>",
        " ",
        " ",
        " \n",
    ]
)


    from_c = parse_diff(TYPICAL_DIFF, ["cpp"], [], [])
    from_py = parse_diff_str(TYPICAL_DIFF, ["cpp"], [], [])


def test_ignored_diff():
    """For coverage completeness"""
    files = parse_diff_str(TYPICAL_DIFF, ["hpp"], [], [])
    # binary files are ignored during parsing
    assert not files