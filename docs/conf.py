# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

from pathlib import Path
import time
from typing import Optional
from importlib.metadata import version as get_version
import docutils
from sphinx.application import Sphinx
from sphinx.util.docutils import SphinxRole
from sphinx_immaterial.inline_icons import load_svg_into_builder_env
from cpp_linter.cli import cli_arg_parser

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
            "accent": "cyan",
            "toggle": {
                "icon": "material/lightbulb-outline",
                "name": "Switch to dark mode",
            },
        },
        {
            "media": "(prefers-color-scheme: dark)",
            "scheme": "slate",
            "primary": "light-blue",
            "accent": "cyan",
            "toggle": {
                "icon": "material/lightbulb",
                "name": "Switch to light mode",
            },
        },
    ],
    "features": [
        "navigation.top",
        # "navigation.tabs",
        # "navigation.tabs.sticky",
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


class CliBadge(SphinxRole):
    badge_type: str
    badge_icon: Optional[str] = None
    href: Optional[str] = None
    href_title: Optional[str] = None

    def run(self):
        permission_link = ""
        if self.badge_type == "permission":
            permission_link, permission = self.text.split(" ", 1)
            self.text = permission
        is_linked = ""
        if self.href is not None and self.href_title is not None:
            is_linked = (
                f'<a href="{self.href}{permission_link or self.text}" '
                + f'title="{self.href_title}">'
            )
        head = '<span class="mdx-badge__icon">'
        if not self.badge_icon:
            head += self.badge_type.title()
        else:
            head += is_linked
            head += (
                f'<span class="md-icon si-icon-inline {self.badge_icon}"></span></a>'
            )
        head += "</span>"
        header = docutils.nodes.raw(
            self.rawtext,
            f'<span class="mdx-badge">{head}<span class="mdx-badge__text">'
            + is_linked
            + (self.text if self.badge_type == "version" else ""),
            format="html",
        )
        if self.badge_type != "version":
            old_highlight = self.inliner.document.settings.syntax_highlight
            self.inliner.document.settings.syntax_highlight = "yaml"
            code, sys_msgs = docutils.parsers.rst.roles.code_role(
                role="code",
                rawtext=self.rawtext,
                text=self.text,
                lineno=self.lineno,
                inliner=self.inliner,
                options={"language": "yaml", "classes": ["highlight"]},
                content=self.content,
            )
            self.inliner.document.settings.syntax_highlight = old_highlight
        else:
            code, sys_msgs = ([], [])
        tail = "</span></span>"
        if self.href is not None and self.href_title is not None:
            tail = "</a>" + tail
        trailer = docutils.nodes.raw(self.rawtext, tail, format="html")
        return ([header, *code, trailer], sys_msgs)


class CliBadgeVersion(CliBadge):
    badge_type = "version"
    href = "https://github.com/cpp-linter/cpp-linter/releases/v"
    href_title = "Required Version"

    def run(self):
        self.badge_icon = load_svg_into_builder_env(
            self.env.app.builder, "material/tag-outline"
        )
        return super().run()


class CliBadgeDefault(CliBadge):
    badge_type = "Default"


class CliBadgePermission(CliBadge):
    badge_type = "permission"
    href = "permissions.html#"
    href_title = "Required Permission"

    def run(self):
        self.badge_icon = load_svg_into_builder_env(
            self.env.app.builder, "material/lock"
        )
        return super().run()


REQUIRED_VERSIONS = {
    "1.7.0": ["tidy_review", "format_review"],
    "1.6.1": ["thread_comments", "no_lgtm"],
    "1.6.0": ["step_summary"],
    "1.4.7": ["extra_arg"],
}

PERMISSIONS = {
    "thread_comments": ["thread-comments", "issues: write"],
    "tidy_review": ["pull-request-reviews", "pull_request: write"],
    "format_review": ["pull-request-reviews", "pull_request: write"],
    "files_changed_only": ["file-changes", "contents: read"],
    "lines_changed_only": ["file-changes", "contents: read"],
}


def setup(app: Sphinx):
    """Generate a doc from the executable script's ``--help`` output."""
    app.add_role("badge-version", CliBadgeVersion())
    app.add_role("badge-default", CliBadgeDefault())
    app.add_role("badge-permission", CliBadgePermission())

    doc = "Command Line Interface Options\n==============================\n\n"
    doc += ".. note::\n\n    These options have a direct relationship with the\n    "
    doc += "`cpp-linter-action user inputs "
    doc += "<https://cpp-linter.github.io/cpp-linter-action/inputs-outputs#inputs>`_. "
    doc += "Although, some default values may differ.\n\n"

    args = cli_arg_parser._optionals._actions
    for arg in args:
        aliases = arg.option_strings
        if not aliases or arg.default == "==SUPPRESS==":
            continue
        doc += "\n.. std:option:: " + ", ".join(aliases) + "\n"
        help = arg.help[: arg.help.find("Defaults to")]
        for ver, names in REQUIRED_VERSIONS.items():
            if arg.dest in names:
                req_ver = ver
                break
        else:
            req_ver = "1.4.6"
        doc += f"\n    :badge-version:`{req_ver}` "
        doc += f":badge-default:`'{arg.default or ''}'` "
        for name, permission in PERMISSIONS.items():
            if name == arg.dest:
                link, spec = permission
                doc += f":badge-permission:`{link} {spec}`"
                break
        doc += "\n\n    "
        doc += "\n    ".join(help.splitlines()) + "\n"
    cli_doc = Path(app.srcdir, "cli_args.rst")
    cli_doc.unlink(missing_ok=True)
    cli_doc.write_text(doc)
