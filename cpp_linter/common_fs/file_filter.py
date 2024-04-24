import configparser
import os
from pathlib import Path, PurePath
from typing import List, Optional, Dict
from . import FileObj
from ..loggers import logger


class FileFilter:
    """A reusable mechanism for parsing and validating file filters.

    :param extensions: A list of file extensions in which to focus.
    :param ignore_value: The user input specified via :std:option:`--ignore` CLI
        argument.
    :param not_ignored: A list of files or paths that will be explicitly not ignored.
    :param tool_specific_name: A clang tool name for which the file filter is
        specifically applied. This only gets used in debug statements.
    """

    def __init__(
        self,
        extensions: List[str],
        ignore_value: str,
        not_ignored: List[str],
        tool_specific_name: Optional[str] = None,
    ) -> None:
        #: A list of file extensions that are considered C/C++ sources.
        self.extensions = extensions
        #: A dict of ignore patterns (keys) mapped to their effects paths (values).
        self.ignored: Dict[str, List[Path]] = {}
        #: A dict of not-ignore patterns (keys) mapped to their effects paths (values).
        self.not_ignored: Dict[str, List[Path]] = {
            f: FileFilter._resolve_glob(f) for f in not_ignored
        }
        self._tool_name = tool_specific_name or ""
        self._parse_ignore_option(paths=ignore_value)

    @staticmethod
    def _resolve_glob(pattern: str):
        if not pattern:
            return [Path(".")]
        return list(Path(".").glob(pattern))

    def parse_submodules(self, path: str = ".gitmodules"):
        """Automatically detect submodules from given ``path``.
        This will add each submodule to the `ignored` list unless already specified as
        `not_ignored`."""
        git_modules = Path(path)
        if git_modules.exists():
            submodules = configparser.ConfigParser()
            submodules.read(git_modules.resolve().as_posix())
            for module in submodules.sections():
                sub_mod_path = submodules[module]["path"]
                if sub_mod_path not in self.not_ignored:
                    logger.info(
                        "Appending submodule to ignored paths: %s", sub_mod_path
                    )
                    self.ignored[sub_mod_path] = [Path(sub_mod_path)]

    def _parse_ignore_option(self, paths: str):
        """Parse a given string of paths (separated by a ``|``) into ``ignored`` and
        ``not_ignored`` lists of strings.

        :param paths: This argument conforms to the input value of CLI arg
            :std:option:`--ignore`.

        Results are added accordingly to the `ignored` and `not_ignored` attributes.
        """
        if paths:
            for path in paths.split("|"):
                path = path.strip()  # strip leading/trailing spaces
                is_included = path.startswith("!")
                if is_included:  # strip leading `!`
                    path = path[1:].lstrip()
                if path.startswith("./"):
                    path = path.replace("./", "", 1)  # relative dir is assumed

                # NOTE: A blank string is now the repo-root `path`
                _glob_result = FileFilter._resolve_glob(path)

                if is_included:
                    self.not_ignored[path] = _glob_result
                else:
                    self.ignored[path] = _glob_result

        tool_name = "" if not self._tool_name else (self._tool_name + " ")
        if self.ignored:
            logger.info(
                "%sIgnoring the following paths/files:\n\t./%s",
                tool_name,
                "\n\t./".join(
                    f.as_posix() for values in self.ignored.values() for f in values
                ),
            )
        if self.not_ignored:
            logger.info(
                "%sNot ignoring the following paths/files:\n\t./%s",
                tool_name,
                "\n\t./".join(
                    f.as_posix() for values in self.not_ignored.values() for f in values
                ),
            )

    def is_file_in_list(self, ignored: bool, file_name: str) -> bool:
        """Determine if a file is specified in a list of paths and/or filenames.

        :param ignored: A flag that specifies which set of list to compare with.
            ``True`` for `ignored` or ``False`` for `not_ignored`.
        :param file_name: The file's path & name being sought in the ``path_list``.

        :returns:

            - True if ``file_name`` is in the ``path_list``.
            - False if ``file_name`` is not in the ``path_list``.
        """
        file_path = PurePath(file_name)
        prompt = "ignored" if ignored else "not ignored"
        tool_name = "" if not self._tool_name else f"[{self._tool_name}] "
        path_list = self.ignored if ignored else self.not_ignored
        for pattern, paths in path_list.items():
            for path in paths:
                if path.is_dir():
                    # if path has no parts, then it is considered repo-root
                    if (
                        not path.parts
                        or PurePath(
                            os.path.commonpath(
                                [f.as_posix() for f in [file_path, path]]
                            )
                        ).as_posix()
                        == path.as_posix()
                    ):
                        logger.debug(
                            '"%s./%s" is %s as specified in the domain "./%s"',
                            tool_name,
                            file_name,
                            prompt,
                            pattern,
                        )
                        return True
                if path.is_file() and path.as_posix() == file_path.as_posix():
                    logger.debug(
                        "%s./%s is %s as specified by pattern ./%s",
                        tool_name,
                        file_name,
                        prompt,
                        pattern,
                    )
                    return True
        return False

    def is_source_or_ignored(self, file_name: str) -> bool:
        """Exclude undesired files (specified by user input :std:option:`--extensions`
        and :std:option:`--ignore` options).

        :param file_name: The name of file in question.

        :returns:
            ``True`` if (in order of precedence)

            .. task-list::
                :custom:

                - [x] ``file_name`` is using one of the specified `extensions`.
                - [x] ``file_name`` is in `not_ignored`.
                - [x] ``file_name`` is not in `ignored`.

            Otherwise ``False``.
        """
        return PurePath(file_name).suffix.lstrip(".") in self.extensions and (
            self.is_file_in_list(ignored=False, file_name=file_name)
            or not self.is_file_in_list(ignored=True, file_name=file_name)
        )

    def list_source_files(self) -> List[FileObj]:
        """Make a list of source files to be checked.
        This will recursively walk the file tree collecting matches to
        anything that would return ``True`` from `is_source_or_ignored()`.

        :returns: A list of `FileObj` objects without diff information.
        """

        root_path = Path(".")
        files = []
        for ext in self.extensions:
            for rel_path in root_path.rglob(f"*.{ext}"):
                for parent in rel_path.parts[:-1]:
                    if parent.startswith("."):
                        break
                else:
                    file_path = rel_path.as_posix()
                    logger.debug('"./%s" is a source code file', file_path)
                    if self.is_file_in_list(
                        ignored=False, file_name=file_path
                    ) or not self.is_file_in_list(ignored=True, file_name=file_path):
                        files.append(FileObj(file_path))
        return files


class TidyFileFilter(FileFilter):
    def __init__(
        self, extensions: List[str], ignore_value: str, not_ignored: List[str]
    ) -> None:
        super().__init__(extensions, ignore_value, not_ignored, "clang-tidy ")


class FormatFileFilter(FileFilter):
    def __init__(
        self, extensions: List[str], ignore_value: str, not_ignored: List[str]
    ) -> None:
        super().__init__(extensions, ignore_value, not_ignored, "clang-format ")
