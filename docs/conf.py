# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import sys
import re
from pathlib import Path
import time
from importlib.metadata import version as get_version
from sphinx.application import Sphinx

sys.path.insert(0, str(Path(__file__).parent.parent))

from cpp_linter.cli import cli_arg_parser  # noqa: E402

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information
project = "cpp-linter"
copyright = f"{time.localtime().tm_year}, 2bndy5"
author = "2bndy5"
release = get_version("cpp-linter")

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
    "pygit2": ("https://www.pygit2.org/", None),
}

autodoc_member_order = "bysource"

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
    "palette": [
        {
            "media": "(prefers-color-scheme: light)",
            "scheme": "default",
            "primary": "light-blue",
            "accent": "deep-purple",
            "toggle": {
                "icon": "material/lightbulb-outline",
                "name": "Switch to dark mode",
            },
        },
        {
            "media": "(prefers-color-scheme: dark)",
            "scheme": "slate",
            "primary": "light-blue",
            "accent": "deep-purple",
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

sphinx_immaterial_custom_admonitions = [
    {
        "name": "seealso",
        "color": (215, 59, 205),
        "icon": "octicons/eye-24",
        "override": True,
    },
    {
        "name": "note",
        "icon": "material/file-document-edit-outline",
        "override": True,
    },
]
for name in ("hint", "tip", "important"):
    sphinx_immaterial_custom_admonitions.append(
        dict(name=name, icon="material/school", override=True)
    )

# -- Parse CLI args from `-h` output -------------------------------------


def setup(app: Sphinx):
    """Generate a doc from the executable script's ``--help`` output."""

    output = cli_arg_parser.format_help()
    first_line = re.search(r"^options:\s*\n", output, re.MULTILINE)
    if first_line is None:
        raise OSError("unrecognized output from `cpp-linter -h`")
    output = output[first_line.end(0) :]
    doc = "Command Line Interface Options\n==============================\n\n"
    doc += ".. note::\n\n    These options have a direct relationship with the\n    "
    doc += "`cpp-linter-action user inputs "
    doc += "<https://github.com/cpp-linter/cpp-linter-action#optional-inputs>`_. "
    doc += "Although, some default values may differ.\n\n"
    CLI_OPT_NAME = re.compile(
        r"^\s*(\-[A-Za-z]+)\s?\{?[A-Za-z_,0-9]*\}?,\s(\-\-[^\s]*?)\s"
    )
    for line in output.splitlines():
        match = CLI_OPT_NAME.search(line)
        if match is not None:
            # print(match.groups())
            doc += "\n.. std:option:: " + ", ".join(match.groups()) + "\n\n"
            options_match = re.search(
                r"\-\w\s\{[a-zA-Z,0-9]+\},\s\-\-[\w\-]+\s\{[a-zA-Z,0-9]+\}", line
            )
            if options_match is not None:
                new_txt = options_match.group()
                line = line.replace(options_match.group(), f"``{new_txt}``")
        doc += line + "\n"
    cli_doc = Path(app.srcdir, "cli_args.rst")
    cli_doc.unlink(missing_ok=True)
    cli_doc.write_text(doc)
