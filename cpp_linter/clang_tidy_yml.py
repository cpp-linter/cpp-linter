"""Parse output from clang-tidy's YML format"""
from pathlib import Path, PurePath
from typing import List, cast, Dict, Any
import yaml
from . import GlobalParser, get_line_cnt_from_cols, logger


CWD_HEADER_GUARD = bytes(
    "_".join([p.upper().replace("-", "_") for p in Path.cwd().parts]), encoding="utf-8"
)  #: The constant used to trim absolute paths from header guard suggestions.


class TidyDiagnostic:
    """Create an object that represents a diagnostic output found in the
    YAML exported from clang-tidy.

    :param diagnostic_name: The name of the check that got triggered.
    """

    def __init__(self, diagnostic_name: str):
        #: The diagnostic name
        self.name = diagnostic_name
        #: The diagnostic message
        self.message = ""
        #: The line number that triggered the diagnostic
        self.line = 0
        #: The columns of the `line` that triggered the diagnostic
        self.cols = 0
        #: The number of bytes replaced by suggestions
        self.null_len = 0
        #: The `list` of `TidyReplacement` objects.
        self.replacements: List["TidyReplacement"] = []

    def __repr__(self):
        """A str representation of all attributes."""
        return (
            f"<TidyDiagnostic {self.name} @ line {self.line} cols {self.cols} : "
            f"{len(self.replacements)} replacements>"
        )


class TidyReplacement:
    """Create an object representing a clang-tidy suggested replacement.

    :param line_cnt: The replacement content's starting line
    :param cols: The replacement content's starting columns
    :param length: The number of bytes discarded from `cols`
    """

    def __init__(self, line_cnt: int, cols: int, length: int):
        #: The replacement content's starting line
        self.line = line_cnt
        #: The replacement content's starting columns
        self.cols = cols
        #: The number of bytes discarded from `cols`
        self.null_len = length
        #: The replacement content's text.
        self.text: bytes = b""

    def __repr__(self) -> str:
        return (
            f"<TidyReplacement @ line {self.line} cols {self.cols} : "
            f"added lines {len(self.text)} discarded bytes {self.null_len}>"
        )


class YMLFixit:
    """A single object to represent each suggestion.

    :param filename: The source file's name (with path) concerning the suggestion.
    """

    def __init__(self, filename: str) -> None:
        #: The source file's name concerning the suggestion.
        self.filename = PurePath(filename).relative_to(Path.cwd()).as_posix()
        #: The `list` of `TidyDiagnostic` objects.
        self.diagnostics: List[TidyDiagnostic] = []

    def __repr__(self) -> str:
        return (
            f"<YMLFixit ({len(self.diagnostics)} diagnostics) for file "
            f"{self.filename}>"
        )


def parse_tidy_suggestions_yml():
    """Read a YAML file from clang-tidy and create a list of suggestions from it.
    Output is saved to :attr:`~cpp_linter.GlobalParser.tidy_advice`.
    """
    yml_file = Path("clang_tidy_output.yml").read_text(encoding="utf-8")
    yml = yaml.safe_load(yml_file)
    fixit = YMLFixit(yml["MainSourceFile"])

    for diag_results in yml["Diagnostics"]:
        diag = TidyDiagnostic(diag_results["DiagnosticName"])
        if "DiagnosticMessage" in cast(Dict[str, Any], diag_results).keys():
            msg = diag_results["DiagnosticMessage"]["Message"]
            offset = diag_results["DiagnosticMessage"]["FileOffset"]
            replacements = diag_results["DiagnosticMessage"]["Replacements"]
        else:  # prior to clang-tidy v9, the YML output was structured differently
            msg = diag_results["Message"]
            offset = diag_results["FileOffset"]
            replacements = diag_results["Replacements"]
        diag.message = msg
        diag.line, diag.cols = get_line_cnt_from_cols(yml["MainSourceFile"], offset)
        for replacement in [] if replacements is None else replacements:
            line_cnt, cols = get_line_cnt_from_cols(
                yml["MainSourceFile"], replacement["Offset"]
            )
            fix = TidyReplacement(line_cnt, cols, replacement["Length"])
            fix.text = bytes(replacement["ReplacementText"], encoding="utf-8")
            if fix.text.startswith(b"header is missing header guard"):
                logger.debug(
                    "filtering header guard suggestion (making relative to repo root)"
                )
                fix.text = fix.text.replace(CWD_HEADER_GUARD, b"")
            diag.replacements.append(fix)
        fixit.diagnostics.append(diag)
        # filter out absolute header guards
    GlobalParser.tidy_advice.append(fixit)
