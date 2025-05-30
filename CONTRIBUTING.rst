Contributing
============

This project requires the following tools installed:

- :si-icon:`simple/uv` `uv (Python Project management tool) <https://docs.astral.sh/uv/>`_

Getting started
---------------

After checking out the repo locally, use

.. code-block:: shell

    uv sync

This creates a venv at ".venv/" in repo root (if it doesn't exist).
It also installs dev dependencies like ``pre-commit``, ``nox``, ``ruff``, and ``mypy``.

See `uv sync docs <https://docs.astral.sh/uv/reference/cli/#uv-sync>`_
for more detailed usage.

.. tip::
    To register the pre-commit hooks, use:

    .. code-block:: shell

        uv run pre-commit install

Running tests
-------------

Use nox to run tests:

.. code-block:: shell

    uv run nox -s test

To run tests in all supported versions of python:

.. code-block:: shell

    uv run nox -s test-all

To generate a coverage report:

.. code-block:: shell

    uv run nox -s coverage

Generating docs
---------------

To view the docs locally, use

.. code-block:: shell

    uv run nox -s docs

Submitting patches
------------------

Be sure to include unit tests for any python code that is changed.
