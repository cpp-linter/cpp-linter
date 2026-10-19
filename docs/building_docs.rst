How to build the docs
=====================

From the root directory of the repository, do the following to steps

1. Install docs' dependencies

   .. code-block:: text

       uv sync --group docs

2. Build the docs

   .. code-block:: text

       uv run sphinx-build docs docs/_build/html

   Alternatively, ``uv run nox -s docs`` does both steps.

   Browse the files in docs/_build/html with your internet browser to see the rendered
   output.
