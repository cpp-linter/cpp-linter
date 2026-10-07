cpp-linter
==========

.. |pypi| image:: https://img.shields.io/pypi/v/cpp-linter?labelColor=454a63&color=007ec6
    :alt: PyPI
    :target: https://pypi.org/project/cpp-linter/
.. |ci| image:: https://img.shields.io/github/actions/workflow/status/cpp-linter/cpp-linter/tests.yml?branch=main&label=ci&labelColor=454a63
    :alt: ci
    :target: https://github.com/cpp-linter/cpp-linter/actions/workflows/tests.yml
.. |coverage| image:: https://img.shields.io/codecov/c/github/cpp-linter/cpp-linter?labelColor=454a63
    :alt: coverage
    :target: https://codecov.io/gh/cpp-linter/cpp-linter
.. |part-of| image:: https://img.shields.io/badge/part%20of-cpp--linter-ffc20a?labelColor=454a63
    :alt: part of cpp-linter
    :target: https://cpp-linter.github.io/

|pypi| |ci| |coverage| |part-of|

The Python command behind cpp-linter-action: it runs clang-format and clang-tidy on C and C++ files, locally or in other CI.

`Website <https://cpp-linter.github.io/>`_ ·
`Documentation <https://cpp-linter.github.io/cpp-linter/>`_ ·
`Get started <https://cpp-linter.github.io/getting-started/#locally-or-in-other-ci>`_ ·
`Discussions <https://github.com/orgs/cpp-linter/discussions>`_

Quick start
-----------

With the clang tools installed (see `Limitations`_):

.. code-block:: shell

    pip install cpp-linter
    cpp-linter --version=21 --style=file --tidy-checks=''

Usage
-----

For usage in a GitHub Actions workflow, see `the cpp-linter/cpp-linter-action repository <https://github.com/cpp-linter/cpp-linter-action>`_

For the description of supported Command Line Interface options, see `the CLI documentation <https://cpp-linter.github.io/cpp-linter/cli_args.html>`_

Applying fixes
--------------

Passing the ``--fix`` option makes cpp-linter apply clang-format fixes in-place to
any files that have formatting problems.

.. note::
    ``--fix`` only applies **clang-format** fixes. clang-tidy fixes are not applied
    automatically.

Limitations
-----------

- cpp-linter does not install the clang tools. Install them first, for example with
  `clang-tools <https://cpp-linter.github.io/clang-tools-pip/>`_; without them, ``--version=21``
  falls back to whatever ``clang-format`` and ``clang-tidy`` are on your ``PATH``.
- It exits 0 even when checks fail, so it reports findings but does not fail a build.
- Locally, ``--files-changed-only`` and ``--lines-changed-only`` read the local git diff. In other CI,
  check the whole repository (the default): most CI systems set ``CI=true``, and with it those
  options ask the GitHub API for the changed files.

Sponsors
--------

cpp-linter is maintained by two volunteers. `Sponsor the project <https://cpp-linter.github.io/sponsor/>`_
through `GitHub Sponsors <https://github.com/sponsors/cpp-linter>`_ or
`Open Collective <https://opencollective.com/cpp-linter>`_. Silver and Gold sponsors get their logo
here.

Contributing
------------

To provide feedback (requesting a feature or reporting a bug) please post to `issues <https://github.com/cpp-linter/cpp-linter/issues>`_. To contribute changes, see `CONTRIBUTING.rst <https://github.com/cpp-linter/cpp-linter/blob/main/CONTRIBUTING.rst>`_.

License
-------

The scripts and documentation in this project are released under the `MIT License <https://github.com/cpp-linter/cpp-linter/blob/main/LICENSE>`_.
