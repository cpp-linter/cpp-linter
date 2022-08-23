# pylint: disable=all
# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import re
from pathlib import Path
import io
from sphinx.application import Sphinx
from cpp_linter.run import cli_arg_parser

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information
project = "cpp-linter"
copyright = "2022, 2bndy5"
author = "2bndy5"
release = "2.0.0"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration
extensions = [
    "sphinx_immaterial",
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinx.ext.viewcode",
]

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "requests": ("https://requests.readthedocs.io/en/latest/", None),
}

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

default_role = "any"

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "sphinx_immaterial"
html_static_path = ["_static"]
html_logo = "_static/logo.png"
html_favicon = "_static/favicon.ico"
html_css_files = ["extra_css.css"]
html_title = "cpp-linter"

html_theme_options = {
    "repo_url": "https://github.com/cpp-linter/cpp-linter",
    "repo_name": "cpp-linter",
    "repo_type": "github",
    "palette": [
        {
            "media": "(prefers-color-scheme: light)",
            "scheme": "default",
            "primary": "indigo",
            "accent": "cyan",
            "toggle": {
                "icon": "material/lightbulb-outline",
                "name": "Switch to dark mode",
            },
        },
        {
            "media": "(prefers-color-scheme: dark)",
            "scheme": "slate",
            "primary": "deep-purple",
            "accent": "cyan",
            "toggle": {
                "icon": "material/lightbulb",
                "name": "Switch to light mode",
            },
        },
    ],
    "features": [
        "navigation.top",
        "navigation.tabs",
        "navigation.tabs.sticky",
        "toc.sticky",
        "toc.follow",
        "search.share",
    ],
}

object_description_options = [
    ("py:parameter", dict(include_in_toc=False)),
]


def setup(app: Sphinx):
    """Generate a doc from the executable script's ``--help`` output."""
    app.add_object_type(
        "cli-opt",
        "cli-opt",
        objname="Command Line Interface option",
        indextemplate="pair: %s; Command Line Interface option",
    )

    with io.StringIO() as help_out:
        cli_arg_parser.print_help(help_out)
        output = help_out.getvalue()
    first_line = re.search(r"^options:\s*\n", output, re.MULTILINE)
    if first_line is None:
        raise OSError("unrecognized output from `cpp-linter -h`")
    output = output[first_line.end(0) :]
    doc = "Command Line Interface Options\n==============================\n\n"
    CLI_OPT_NAME = re.compile(r"^\s+(\-+\w)[\sA-Z_]*,\s(\-\-.*?)\s")
    for line in output.splitlines():
        match = CLI_OPT_NAME.search(line)
        if match is not None:
            # print(match.groups())
            doc += "\n.. cli-opt:: " + ", ".join(match.groups()) + "\n\n"
        doc += line + "\n"
    cli_doc = Path(app.srcdir, "cli_args.rst")
    cli_doc.unlink(missing_ok=True)
    cli_doc.write_text(doc)
