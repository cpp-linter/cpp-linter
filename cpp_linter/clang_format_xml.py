"""Parse output from clang-format's XML suggestions."""
from pathlib import PurePath
from typing import List, Optional
import xml.etree.ElementTree as ET
from . import GlobalParser, get_line_cnt_from_cols


class FormatReplacement:
    """An object representing a single replacement.

    :param cols: The columns number of where the suggestion starts on the line
    :param null_len: The number of bytes removed by suggestion
    :param text: The `bytearray` of the suggestion
    """

    def __init__(self, cols: int, null_len: int, text: str) -> None:
        #: The columns number of where the suggestion starts on the line
        self.cols = cols
        #: The number of bytes removed by suggestion
        self.null_len = null_len
        #: The `bytearray` of the suggestion
        self.text = text

    def __repr__(self) -> str:
        return (
            f"<FormatReplacement at cols {self.cols} removes {self.null_len} bytes"
            f" adds {len(self.text)} bytes>"
        )


class FormatReplacementLine:
    """An object that represents a replacement(s) for a single line.

    :param line_numb: The line number of about the replacements
    """

    def __init__(self, line_numb: int):
        #: The line number of where the suggestion starts
        self.line = line_numb

        #: A list of `FormatReplacement` object(s) representing suggestions.
        self.replacements: List[FormatReplacement] = []

    def __repr__(self):
        return (
            f"<FormatReplacementLine @ line {self.line} "
            f"with {len(self.replacements)} replacements>"
        )


class XMLFixit:
    """A single object to represent each suggestion.

    :param filename: The source file's name for which the contents of the xml
        file exported by clang-tidy.
    """

    def __init__(self, filename: str):
        """ """
        #: The source file that the suggestion concerns.
        self.filename = PurePath(filename).as_posix()

        self.replaced_lines: List[FormatReplacementLine] = []
        """A list of `FormatReplacementLine` representing replacement(s)
        on a single line."""

    def __repr__(self) -> str:
        return (
            f"<XMLFixit with {len(self.replaced_lines)} lines of "
            f"replacements for {self.filename}>"
        )

    def log_command(self, style: str, line_filter: List[int]) -> Optional[str]:
        """Output a notification as a github log command.

        .. seealso::

            - `An error message <https://docs.github.com/en/actions/learn-github-
              actions/workflow-commands-for-github-actions#setting-an-error-message>`_
            - `A warning message <https://docs.github.com/en/actions/learn-github-
              actions/workflow-commands-for-github-actions#setting-a-warning-message>`_
            - `A notice message <https://docs.github.com/en/actions/learn-github-
              actions/workflow-commands-for-github-actions#setting-a-notice-message>`_

        :param style: The chosen code style guidelines.
        :param line_filter: A list of lines numbers used to narrow notifications.
        """
        if style not in (
            "llvm", "gnu", "google", "chromium", "microsoft", "mozilla", "webkit"
            ):
            # potentially the style parameter could be a str of JSON/YML syntax
            style = "Custom"
        else:
            if style.startswith("llvm") or style.startswith("gnu"):
                style = style.upper()
            else:
                style = style.title()
        line_list = []
        for fix in self.replaced_lines:
            if not line_filter or (line_filter and fix.line in line_filter):
                line_list.append(str(fix.line))
        if not line_list:
            return None
        return (
            "::notice file={name},title=Run clang-format on {name}::"
            "File {name} (lines {lines}): Code does not conform to {style_guide} "
            "style guidelines.".format(
                name=self.filename,
                lines=", ".join(line_list),
                style_guide=style,
            )
        )


def parse_format_replacements_xml(src_filename: str):
    """Parse XML output of replacements from clang-format. Output is saved to
    :attr:`~cpp_linter.GlobalParser.format_advice`.

    :param src_filename: The source file's name for which the contents of the xml
            file exported by clang-tidy.
    """
    tree = ET.parse("clang_format_output.xml")
    fixit = XMLFixit(src_filename)
    for child in tree.getroot():
        if child.tag == "replacement":
            offset = int(child.attrib["offset"])
            line, cols = get_line_cnt_from_cols(src_filename, offset)
            null_len = int(child.attrib["length"])
            text = "" if child.text is None else child.text
            fix = FormatReplacement(cols, null_len, text)
            if not fixit.replaced_lines or (
                fixit.replaced_lines and line != fixit.replaced_lines[-1].line
            ):
                line_fix = FormatReplacementLine(line)
                line_fix.replacements.append(fix)
                fixit.replaced_lines.append(line_fix)
            elif fixit.replaced_lines and line == fixit.replaced_lines[-1].line:
                fixit.replaced_lines[-1].replacements.append(fix)
    GlobalParser.format_advice.append(fixit)
