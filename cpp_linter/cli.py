"""Setup the options for :doc:`CLI <../cli_args>` arguments."""

import argparse
from collections import UserDict
from typing import Optional, List, Dict, Any, Sequence


class Args(UserDict):
    """A pseudo namespace declaration. Each attribute is initialized with the
    corresponding :doc:`CLI <../cli_args>` arg's default value."""

    #: See :std:option:`--verbosity`.
    verbosity: bool = False
    #: See :std:option:`--database`.
    database: str = ""
    #: See :std:option:`--style`.
    style: str = "llvm"
    #: See :std:option:`--tidy-checks`.
    tidy_checks: str = (
        "boost-*,bugprone-*,performance-*,readability-*,portability-*,modernize-*,"
        "clang-analyzer-*,cppcoreguidelines-*"
    )
    #: See :std:option:`--version`.
    version: str = ""
    #: See :std:option:`--extensions`.
    extensions: List[str] = [
        "c",
        "h",
        "C",
        "H",
        "cpp",
        "hpp",
        "cc",
        "hh",
        "c++",
        "h++",
        "cxx",
        "hxx",
    ]
    #: See :std:option:`--repo-root`.
    repo_root: str = "."
    #: See :std:option:`--ignore`.
    ignore: str = ".github"
    #: See :std:option:`--lines-changed-only`.
    lines_changed_only: int = 0
    #: See :std:option:`--files-changed-only`.
    files_changed_only: bool = False
    #: See :std:option:`--thread-comments`.
    thread_comments: str = "false"
    #: See :std:option:`--step-summary`.
    step_summary: bool = False
    #: See :std:option:`--file-annotations`.
    file_annotations: bool = True
    #: See :std:option:`--extra-arg`.
    extra_arg: List[str] = []
    #: See :std:option:`--no-lgtm`.
    no_lgtm: bool = True
    #: See :std:option:`files`.
    files: List[str] = []
    #: See :std:option:`--tidy-review`.
    tidy_review: bool = False
    #: See :std:option:`--format-review`.
    format_review: bool = False
    #: See :std:option:`--jobs`.
    jobs: Optional[int] = 1
    #: See :std:option:`--ignore-tidy`.
    ignore_tidy: str = ""
    #: See :std:option:`--ignore-format`.
    ignore_format: str = ""
    #: See :std:option:`--passive-reviews`.
    passive_reviews: bool = False


_parser_args: Dict[Sequence[str], Any] = {}
_parser_args[("-v", "--verbosity")] = dict(
    type=lambda a: a.lower() in ["debug", "10"],
    default="info",
    help="""This controls the action's verbosity in the workflow's
logs. Supported options are ``debug`` and ``info``.
The numerical representations of these log levels
defined by the `logging <logging-levels>`_ library
(``10`` for ``debug``, and ``20`` for ``info``) are
also supported.

This option does not affect the verbosity of resulting
thread comments, file annotations, nor log grouping
markers.

Defaults to level ``%(default)s``""",
)
_parser_args[("-p", "--database")] = dict(
    default="",
    help="""The path that is used to read a compile command
database. For example, it can be a CMake build
directory in which a file named compile_commands.json
exists (set ``CMAKE_EXPORT_COMPILE_COMMANDS`` to
``ON``). When no build path is specified, a search
for compile_commands.json will be attempted through
all parent paths of the first input file. See
https://clang.llvm.org/docs/HowToSetupToolingForLLVM.html
for an example of setting up Clang Tooling on a source
tree.

.. important::
    Builds using ninja should explicitly specify this
    path. Otherwise, cpp-linter will have difficulty
    parsing clang-tidy output.""",
)
_parser_args[("-s", "--style")] = dict(
    default="llvm",
    help="""The style rules to use.

- Set this to ``file`` to have clang-format use the
  closest relative .clang-format file.
- Set this to a blank string (``""``) to disable
  using clang-format entirely.

See `clang-format docs <https://clang.llvm.org/docs/ClangFormat.html>`_ for more info.

.. note::
    If this is not a blank string, then it is also
    passed to clang-tidy (if :std:option:`--tidy-checks`
    is not ``-*``). This is done ensure a more consistent
    output about suggested fixes between clang-tidy and
    clang-format.

Defaults to ``%(default)s``""",
)
_parser_args[("-c", "--tidy-checks")] = dict(
    default="boost-*,bugprone-*,performance-*,readability-*,portability-*,modernize-*,"
    "clang-analyzer-*,cppcoreguidelines-*",
    help="""A comma-separated list of globs with optional
``-`` prefix. Globs are processed in order of
appearance in the list. Globs without ``-`` prefix
add checks with matching names to the set, globs with
the ``-`` prefix remove checks with matching names
from the set of enabled checks. This option's value
is appended to the value of the 'Checks' option in
a .clang-tidy file (if any).

- It is possible to disable clang-tidy entirely by
  setting this option to ``'-*'``.
- It is also possible to rely solely on a .clang-tidy
  config file by specifying this option as a blank
  string (``''``).

See also `clang-tidy docs <https://clang.llvm.org/extra/clang-tidy>`_ for more info.

Defaults to:
    %(default)s
""",
)
_parser_args[("-V", "--version")] = dict(
    default="",
    help="""The desired version of the clang tools to use.

- Set this option to a blank string (``''``) to use
  the platform's default installed version.
- This value can also be a path to where the clang
  tools are installed (if using a custom install
  location). All paths specified here are converted
  to absolute.

Defaults to ``''``""",
)
_parser_args[("-e", "--extensions")] = dict(
    default="c,h,C,H,cpp,hpp,cc,hh,c++,h++,cxx,hxx",
    type=lambda i: [ext.strip().lstrip(".") for ext in i.split(",")],
    help="""The file extensions to analyze.
This is a comma-separated string of extensions.
Defaults to:
    %(default)s
""",
)
_parser_args[("-r", "--repo-root")] = dict(
    default=".",
    help="""The relative path to the repository root directory.
This path is relative to the working directory from
which cpp-linter was executed.
Defaults to ``%(default)s``""",
)
_parser_args[("-i", "--ignore")] = dict(
    default=".github",
    help="""Set this option with path(s) to ignore (or not ignore).

- In the case of multiple paths, you can use ``|`` to
  separate each path.
- There is no need to use ``./`` for each entry; a
  blank string (``''``) represents the
  :std:option:`--repo-root` path.
- This can also have files, but the file's path
  (relative to the :std:option:`--repo-root`) has to
  be specified with the filename.
- Submodules are automatically ignored. Hidden
  directories (beginning with a ``.``) are also
  ignored automatically.
- Prefix a path with ``!`` to explicitly not ignore
  it. This can be applied to a submodule's path (if
  desired) but not hidden directories.
- .. versionadded:: 1.9 Glob patterns are supported
      here.
      :collapsible:

      All asterisk characters (``*``) are not literal
      as they were before. See
      :py:meth:`~pathlib.Path.glob()` for more details
      about Unix style glob patterns.
""",
)
_parser_args[("-M", "--ignore-format")] = dict(
    default="",
    help="""Set this option with path(s) to ignore (or not ignore)
when using clang-format. See :std:option:`--ignore` for
more detail.""",
)
_parser_args[("-D", "--ignore-tidy")] = dict(
    default="",
    help="""Set this option with path(s) to ignore (or not ignore)
when using clang-tidy. See :std:option:`--ignore` for
more detail.""",
)
_parser_args[("-l", "--lines-changed-only")] = dict(
    default="false",
    type=lambda a: 2 if a.lower() == "true" else int(a.lower() == "diff"),
    help="""This controls what part of the files are analyzed.
The following values are accepted:

- ``false``: All lines in a file are analyzed.
- ``true``: Only lines in the diff that contain
  additions are analyzed.
- ``diff``: All lines in the diff are analyzed
  including unchanged lines but not subtractions.

Defaults to ``%(default)s``.""",
)
_parser_args[("-f", "--files-changed-only")] = dict(
    default="false",
    type=lambda input: input.lower() == "true",
    help="""Set this option to false to analyze any source
files in the repo. This is automatically enabled if
:std:option:`--lines-changed-only` is enabled.

.. note::
    The ``GITHUB_TOKEN`` should be supplied when
    running on a private repository with this option
    enabled, otherwise the runner does not not have
    the privilege to list the changed files for an
    event.

    See `Authenticating with the GITHUB_TOKEN
    <https://docs.github.com/en/actions/reference/authentication-in-a-workflow>`_

Defaults to ``%(default)s``.""",
)
_parser_args[("-g", "--no-lgtm")] = dict(
    default="true",
    type=lambda input: input.lower() == "true",
    help="""Set this option to true or false to enable or
disable the use of a thread comment or PR review
that basically says 'Looks Good To Me' (when all
checks pass).

.. seealso::
    The :std:option:`--thread-comments` option also
    notes further implications.

Defaults to ``%(default)s``.""",
)
_parser_args[("-t", "--thread-comments")] = dict(
    default="false",
    choices=["true", "false", "update"],
    help="""This controls the behavior of posted thread
comments as feedback.
The following options are supported:

- ``true``: enable the use of thread comments.
  This will always delete an outdated thread
  comment and post a new comment (triggering
  a notification for every comment).
- ``update``: update an existing thread comment
  if one already exists. This option does not
  trigger a new notification for every thread
  comment update.
- ``false``: disable the use of thread comments.

.. note::
    To use thread comments, the ``GITHUB_TOKEN``
    (provided by Github to each repository) must
    be declared as an environment variable.

    See `Authenticating with the GITHUB_TOKEN
    <https://docs.github.com/en/actions/reference/authentication-in-a-workflow>`_

Defaults to ``%(default)s``.""",
)
_parser_args[("-w", "--step-summary")] = dict(
    default="false",
    type=lambda input: input.lower() == "true",
    help="""Set this option to true or false to enable or
disable the use of a workflow step summary when the run
has concluded.

Defaults to ``%(default)s``.""",
)
_parser_args[("-a", "--file-annotations")] = dict(
    default="true",
    type=lambda input: input.lower() == "true",
    help="""Set this option to false to disable the use of
file annotations as feedback.

Defaults to ``%(default)s``.""",
)
_parser_args[("-x", "--extra-arg")] = dict(
    default=[],
    action="append",
    help="""A string of extra arguments passed to clang-tidy
for use as compiler arguments. This can be specified
more than once for each additional argument. Recommend
using quotes around the value and avoid using spaces
between name and value (use ``=`` instead):

.. code-block:: shell

    cpp-linter --extra-arg="-std=c++17" --extra-arg="-Wall"

Defaults to none.
""",
)
_parser_args[("files",)] = dict(
    nargs="*",
    help="""
A space separated list of files to focus on.
These files will automatically be added to the list of
explicitly not-ignored files. While other filtering is
done with :std:option:`--extensions`, the files
specified as positional arguments will be exempt from
explicitly ignored domains (see :std:option:`--ignore`).""",
)
_parser_args[("-d", "--tidy-review")] = dict(
    default="false",
    type=lambda input: input.lower() == "true",
    help="""Set to ``true`` to enable Pull Request reviews
from clang-tidy.

Defaults to ``%(default)s``.""",
)
_parser_args[("-m", "--format-review")] = dict(
    default="false",
    type=lambda input: input.lower() == "true",
    help="""Set to ``true`` to enable Pull Request reviews
from clang-format.

Defaults to ``%(default)s``.""",
)
_parser_args[("-R", "--passive-reviews")] = dict(
    default="false",
    type=lambda input: input.lower() == "true",
    help="""Set to ``true`` to prevent Pull Request
reviews from requesting or approving changes.""",
)


def _parse_jobs(val: str) -> Optional[int]:
    try:
        jobs = int(val)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid -j (--jobs) value: {val} (must be an integer)"
        ) from exc

    if jobs <= 0:
        return None  # let multiprocessing.Pool decide the number of workers

    return jobs


_parser_args[("-j", "--jobs")] = dict(
    default=1,
    type=_parse_jobs,
    help="""Set the number of jobs to run simultaneously.
If set less than or equal to 0, the number of jobs will
be set to the number of all available CPU cores.

Defaults to ``%(default)s``.""",
)


def get_cli_parser() -> argparse.ArgumentParser:
    cli_parser = argparse.ArgumentParser(
        description=(
            "Run clang-tidy and clang-format on a list of changed files "
            + "provided by GitHub's REST API."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    for switches, kwargs in _parser_args.items():
        cli_parser.add_argument(*switches, **kwargs)
    return cli_parser
