"""Setup the options for CLI arguments."""
import argparse
import logging

cli_arg_parser = argparse.ArgumentParser(
    description="Run clang-tidy and clang-format on a list of changed files "
    "provided by GitHub's REST API.",
    formatter_class=argparse.RawTextHelpFormatter,
)
arg = cli_arg_parser.add_argument(
    "-v",
    "--verbosity",
    type=int,
    default=10,
    help="""This controls the action's verbosity in the workflow's logs.
Supported options are defined by the `logging-level <logging-levels>`_.
This option does not affect the verbosity of resulting
thread comments or file annotations.

Defaults to level ``%(default)s`` (aka  """,
)
assert arg.help is not None
arg.help += f"``logging.{logging.getLevelName(arg.default)}``)."
cli_arg_parser.add_argument(
    "-p",
    "--database",
    default="",
    help="""The path that is used to read a compile command database.
For example, it can be a CMake build directory in which a file named
compile_commands.json exists (set ``CMAKE_EXPORT_COMPILE_COMMANDS`` to ``ON``).
When no build path is specified, a search for compile_commands.json will be
attempted through all parent paths of the first input file. See
https://clang.llvm.org/docs/HowToSetupToolingForLLVM.html for an
example of setting up Clang Tooling on a source tree.""",
)
cli_arg_parser.add_argument(
    "-s",
    "--style",
    default="llvm",
    help="""The style rules to use (defaults to ``%(default)s``).

- Set this to ``file`` to have clang-format use the closest relative
  .clang-format file.
- Set this to a blank string (``""``) to disable using clang-format
  entirely.""",
)
cli_arg_parser.add_argument(
    "-c",
    "--tidy-checks",
    default="boost-*,bugprone-*,performance-*,readability-*,portability-*,modernize-*,"
    "clang-analyzer-*,cppcoreguidelines-*",
    help="""A comma-separated list of globs with optional ``-`` prefix.
Globs are processed in order of appearance in the list.
Globs without ``-`` prefix add checks with matching names to the set,
globs with the ``-`` prefix remove checks with matching names from the set of
enabled checks. This option's value is appended to the value of the 'Checks'
option in a .clang-tidy file (if any).

- It is possible to disable clang-tidy entirely by setting this option to ``'-*'``.
- It is also possible to rely solely on a .clang-tidy config file by
  specifying this option as a blank string (``''``).

The defaults is::

    %(default)s

See also clang-tidy docs for more info.""",
)
arg = cli_arg_parser.add_argument(
    "-V",
    "--version",
    default="",
    help="""The desired version of the clang tools to use. Accepted options are
strings which can be 8, 9, 10, 11, 12, 13, 14, 15.

- Set this option to a blank string (``''``) to use the
  platform's default installed version.
- This value can also be a path to where the clang tools are
  installed (if using a custom install location). All paths specified
  here are converted to absolute.

Default is """,
)
assert arg.help is not None
arg.help += "a blank string." if not arg.default else f"``{arg.default}``."
arg = cli_arg_parser.add_argument(
    "-e",
    "--extensions",
    default=["c", "h", "C", "H", "cpp", "hpp", "cc", "hh", "c++", "h++", "cxx", "hxx"],
    type=lambda i: [ext.strip().lstrip(".") for ext in i.split(",")],
    help="""The file extensions to analyze.
This comma-separated string defaults to::

    """,
)
assert arg.help is not None
arg.help += ",".join(arg.default) + "\n"
cli_arg_parser.add_argument(
    "-r",
    "--repo-root",
    default=".",
    help="""The relative path to the repository root directory. This path is
relative to the runner's ``GITHUB_WORKSPACE`` environment variable (or
the current working directory if not using a CI runner).

The default value is ``%(default)s``""",
)
cli_arg_parser.add_argument(
    "-i",
    "--ignore",
    default=".github",
    help="""Set this option with path(s) to ignore (or not ignore).

- In the case of multiple paths, you can use ``|`` to separate each path.
- There is no need to use ``./`` for each entry; a blank string (``''``)
  represents the repo-root path.
- This can also have files, but the file's path (relative to
  the :std:option:`--repo-root`) has to be specified with the filename.
- Submodules are automatically ignored. Hidden directories (beginning
  with a ``.``) are also ignored automatically.
- Prefix a path with ``!`` to explicitly not ignore it. This can be
  applied to a submodule's path (if desired) but not hidden directories.
- Glob patterns are not supported here. All asterisk characters (``*``)
  are literal.""",
)
arg = cli_arg_parser.add_argument(
    "-l",
    "--lines-changed-only",
    default=0,
    type=lambda a: 2 if a.lower() == "true" else int(a.lower() == "diff"),
    help="""This controls what part of the files are analyzed.
The following values are accepted:

- false: All lines in a file are analyzed.
- true: Only lines in the diff that contain additions are analyzed.
- diff: All lines in the diff are analyzed (including unchanged
  lines but not subtractions).

Defaults to """,
)
assert arg.help is not None
arg.help += f"``{str(bool(arg.default)).lower()}``."
cli_arg_parser.add_argument(
    "-f",
    "--files-changed-only",
    default="false",
    type=lambda input: input.lower() == "true",
    help="""Set this option to false to analyze any source files in the repo.
This is automatically enabled if
:std:option:`--lines-changed-only` is enabled.

.. note::
    The ``GITHUB_TOKEN`` should be supplied when running on a
    private repository with this option enabled, otherwise the runner
    does not not have the privilege to list the changed files for an event.

    See `Authenticating with the GITHUB_TOKEN
    <https://docs.github.com/en/actions/reference/authentication-in-a-workflow>`_

Defaults to ``%(default)s``.""",
)
cli_arg_parser.add_argument(
    "-t",
    "--thread-comments",
    default="false",
    type=lambda input: input.lower() == "true",
    help="""Set this option to true or false to enable or disable the use of
thread comments as feedback.

.. note::
    To use thread comments, the ``GITHUB_TOKEN`` (provided by
    Github to each repository) must be declared as an environment
    variable.

    See `Authenticating with the GITHUB_TOKEN
    <https://docs.github.com/en/actions/reference/authentication-in-a-workflow>`_

.. hint::
    If run on a private repository, then this feature is
    disabled because the GitHub REST API behaves
    differently for thread comments on a private repository.

Defaults to ``%(default)s``.""",
)
cli_arg_parser.add_argument(
    "-a",
    "--file-annotations",
    default="true",
    type=lambda input: input.lower() == "true",
    help="""Set this option to false to disable the use of
file annotations as feedback.

Defaults to ``%(default)s``.""",
)
cli_arg_parser.add_argument(
    "-x",
    "--extra-arg",
    default=[],
    action="append",
    help="""A string of extra arguments passed to clang-tidy for use as
compiler arguments. This can be specified more than once for each
additional argument. Recommend using quotes around the value and
avoid using spaces between name and value (use ``=`` instead):

.. code-block:: shell

    cpp-linter --extra-arg="-std=c++17" --extra-arg="-Wall"

Defaults to ``'%(default)s'``.
""",
)
