"""Parse output from clang-format's XML suggestions."""

from pathlib import PurePath
import subprocess
from typing import List, cast

import xml.etree.ElementTree as ET

from ..common_fs import get_line_cnt_from_cols, FileObj
from ..loggers import logger
from .patcher import PatchMixin


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


class FormatAdvice(PatchMixin):
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

        super().__init__()

    def __repr__(self) -> str:
        return (
            f"<XMLFixit with {len(self.replaced_lines)} lines of "
            f"replacements for {self.filename}>"
        )

    def get_suggestion_help(self, start, end) -> str:
        return super().get_suggestion_help(start, end) + "suggestion\n"

    def get_tool_name(self) -> str:
        return "clang-format"


def tally_format_advice(files: List[FileObj]) -> int:
    """Returns the sum of clang-format errors"""
    format_checks_failed = 0
    for file_obj in files:
        if not file_obj.format_advice:
            continue
        if file_obj.format_advice.replaced_lines:
            format_checks_failed += 1
    return format_checks_failed


def formalize_style_name(style: str) -> str:
    if style.startswith("llvm") or style.startswith("gnu"):
        return style.upper()
    if style in (
        "google",
        "chromium",
        "microsoft",
        "mozilla",
        "webkit",
    ):
        return style.title()
    # potentially the style parameter could be a str of JSON/YML syntax
    return "Custom"


def parse_format_replacements_xml(
    xml_out: str, file_obj: FileObj, lines_changed_only: int
) -> FormatAdvice:
    """Parse XML output of replacements from clang-format.

    :param xml_out: A string containing the XML output.
    :param file_obj: The source file's info for which the contents of the xml
        that was exported by clang-format.
    :param lines_changed_only: A flag that forces focus on only changes in the event's
        diff info.
    """
    format_advice = FormatAdvice(file_obj.name)
    if not xml_out:
        return format_advice
    ranges = cast(
        List[List[int]],
        file_obj.range_of_changed_lines(lines_changed_only, get_ranges=True),
    )
    tree = ET.fromstring(xml_out)
    for child in tree:
        if child.tag == "replacement":
            null_len = int(child.attrib["length"])
            text = "" if child.text is None else child.text
            offset = int(child.attrib["offset"])
            line, cols = get_line_cnt_from_cols(file_obj.name, offset)
            is_line_in_ranges = False
            for r in ranges:
                if line in range(r[0], r[1]):  # range is inclusive
                    is_line_in_ranges = True
                    break
            if is_line_in_ranges or lines_changed_only == 0:
                fix = FormatReplacement(cols, null_len, text)
                if not format_advice.replaced_lines or (
                    format_advice.replaced_lines
                    and line != format_advice.replaced_lines[-1].line
                ):
                    line_fix = FormatReplacementLine(line)
                    line_fix.replacements.append(fix)
                    format_advice.replaced_lines.append(line_fix)
                elif (
                    format_advice.replaced_lines
                    and line == format_advice.replaced_lines[-1].line
                ):
                    format_advice.replaced_lines[-1].replacements.append(fix)
    return format_advice


def run_clang_format(
    command: str,
    file_obj: FileObj,
    style: str,
    lines_changed_only: int,
    format_review: bool,
) -> FormatAdvice:
    """Run clang-format on a certain file

    :param command: The clang-format command to use (usually a resolved path).
    :param file_obj: Information about the `FileObj`.
    :param style: The clang-format style rules to adhere. Set this to 'file' to
        use the relative-most .clang-format configuration file.
    :param lines_changed_only: A flag that forces focus on only changes in the event's
        diff info.
    :param format_review: A flag to enable/disable creating a diff suggestion for
        PR review comments.
    """
    cmds = [
        command,
        f"-style={style}",
        "--output-replacements-xml",
    ]
    ranges = cast(
        List[List[int]],
        file_obj.range_of_changed_lines(lines_changed_only, get_ranges=True),
    )
    for span in ranges:
        cmds.append(f"--lines={span[0]}:{span[1]}")
    cmds.append(PurePath(file_obj.name).as_posix())
    logger.info('Running "%s"', " ".join(cmds))
    results = subprocess.run(cmds, capture_output=True)
    if results.returncode:
        logger.debug(
            "%s raised the following error(s):\n%s", cmds[0], results.stderr.decode()
        )
    advice = parse_format_replacements_xml(
        results.stdout.decode(encoding="utf-8").strip(), file_obj, lines_changed_only
    )
    if format_review:
        del cmds[2]  # remove `--output-replacements-xml` flag
        logger.info('Getting fixes with "%s"', " ".join(cmds))
        # get formatted file from stdout
        formatted_output = subprocess.run(cmds, capture_output=True, check=True)
        # store formatted_output (for comparing later)
        advice.patched = formatted_output.stdout
    return advice
