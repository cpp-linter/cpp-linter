"""Nox automation file for cpp-linter project.

This file defines automation sessions for testing, coverage, and documentation
using uv for dependency management and virtual environment backend.
"""

import logging
from os import environ
import sys
import nox

ci_logger = logging.getLogger("CI logger")
ci_handler = logging.StreamHandler(stream=sys.stdout)
ci_handler.formatter = logging.Formatter("%(msg)s")
ci_logger.handlers.append(ci_handler)
ci_logger.propagate = False

nox.options.default_venv_backend = "uv"
nox.options.reuse_existing_virtualenvs = True


def uv_sync(session: nox.Session, *args: str):
    """Synchronize dependencies using uv with additional arguments.

    Args:
        session: The nox session to run the command in.
        *args: Additional arguments to pass to `uv sync`.
    """
    session.run_install(
        "uv",
        "sync",
        "--active",
        *args,
    )


@nox.session
def docs(session: nox.Session):
    """Build the docs with sphinx."""
    uv_sync(session, "--group", "docs")
    session.run("sphinx-build", "docs", "docs/_build/html")


def run_tests(session: nox.Session):
    """Run the unit tests"""
    uv_sync(session, "--group", "test")
    session.run(
        "uv", "run", "--active", "coverage", "run", "-m", "pytest", *session.posargs
    )


@nox.session
def test(session: nox.Session):
    """Run unit tests."""
    run_tests(session)


MAX_VERSION = environ.get("MAX_PYTHON_VERSION", "3.14")


@nox.session(
    name="test-all",
    python=nox.project.python_versions(
        nox.project.load_toml("pyproject.toml"),
        max_version=MAX_VERSION,
    ),
)
def test_all(session: nox.Session):
    """Run unit tests in all supported version of python and clang"""
    ci_logger.info("::group::Using Python %s" % session.python)
    run_tests(session)
    ci_logger.info("::endgroup::")


@nox.session
def coverage(session: nox.Session):
    """Create coverage report."""
    uv_sync(session, "--group", "test")
    ci_logger.info("::group::Combining coverage data")
    session.run("uv", "run", "--active", "coverage", "combine")
    ci_logger.info("::endgroup::")
    session.run("uv", "run", "--active", "coverage", "html")
    session.run("uv", "run", "--active", "coverage", "xml")
    session.run("uv", "run", "--active", "coverage", "report")
