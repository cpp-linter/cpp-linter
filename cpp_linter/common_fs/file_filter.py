import configparser
from pathlib import Path, PurePath
from typing import List, Optional, Set
from . import FileObj
from ..loggers import logger


class FileFilter:
    """A reusable mechanism for parsing and validating file filters.

    :param extensions: A list of file extensions in which to focus.
    :param ignore_value: The user input specified via :std:option:`--ignore`
        CLI argument.
    :param not_ignored: A list of files or paths that will be explicitly not ignored.
    :param tool_specific_name: A clang tool name for which the file filter is
        specifically applied. This only gets used in debug statements.
    """

    def __init__(
        self,
        ignore_value: str = "",
        extensions: Optional[List[str]] = None,
        not_ignored: Optional[List[str]] = None,
        tool_specific_name: Optional[str] = None,
    ) -> None:
        #: A set of file extensions that are considered C/C++ sources.
        self.extensions: Set[str] = set(extensions or [])
        #: A set of ignore patterns.
        self.ignored: Set[str] = set()
        #: A set of not-ignore patterns.
        self.not_ignored: Set[str] = set(not_ignored or [])
        self._tool_name = tool_specific_name or ""
        self._parse_ignore_option(paths=ignore_value)

    def parse_submodules(self, path: str = ".gitmodules"):
        """Automatically detect submodules from the given relative ``path``.
        This will add each submodule to the `ignored` list unless already specified as
        `not_ignored`."""
        git_modules = Path(path)
        if git_modules.exists():
            git_modules_parent = git_modules.parent
            submodules = configparser.ConfigParser()
            submodules.read(git_modules.resolve().as_posix())
            for module in submodules.sections():
                sub_mod_path = git_modules_parent / submodules[module]["path"]
                if not self.is_file_in_list(ignored=False, file_name=sub_mod_path):
                    sub_mod_posix = sub_mod_path.as_posix()
                    logger.info(
                        "Appending submodule to ignored paths: %s", sub_mod_posix
                    )
                    self.ignored.add(sub_mod_posix)

    def _parse_ignore_option(self, paths: str):
        """Parse a given string of paths (separated by a ``|``) into ``ignored`` and
        ``not_ignored`` lists of strings.

        :param paths: This argument conforms to the input value of :doc:`:doc:`CLI <cli_args>` <cli_args>` arg
            :std:option:`--ignore`.

        Results are added accordingly to the `ignored` and `not_ignored` attributes.
        """
        for path in paths.split("|") if paths else []:
            path = path.strip()  # strip leading/trailing spaces
            is_included = path.startswith("!")
            if is_included:  # strip leading `!`
                path = path[1:].lstrip()
            if path.startswith("./"):
                path = path.replace("./", "", 1)  # relative dir is assumed

            # NOTE: A blank string is now the repo-root `path`

            if is_included:
                self.not_ignored.add(path)
            else:
                self.ignored.add(path)

        tool_name = "" if not self._tool_name else (self._tool_name + " ")
        if self.ignored:
            logger.info(
                "%sIgnoring the following paths/files/patterns:\n\t./%s",
                tool_name,
                "\n\t./".join(PurePath(p).as_posix() for p in self.ignored),
            )
        if self.not_ignored:
            logger.info(
                "%sNot ignoring the following paths/files/patterns:\n\t./%s",
                tool_name,
                "\n\t./".join(PurePath(p).as_posix() for p in self.not_ignored),
            )

    def is_file_in_list(self, ignored: bool, file_name: PurePath) -> bool:
        """Determine if a file is specified in a list of paths and/or filenames.

        :param ignored: A flag that specifies which set of list to compare with.
            ``True`` for `ignored` or ``False`` for `not_ignored`.
        :param file_name: The file's path & name being sought in the ``path_list``.

        :returns:

            - True if ``file_name`` is in the ``path_list``.
            - False if ``file_name`` is not in the ``path_list``.
        """
        prompt = "not ignored"
        path_list = self.not_ignored
        if ignored:
            prompt = "ignored"
            path_list = self.ignored
        tool_name = "" if not self._tool_name else f"[{self._tool_name}] "
        prompt_pattern = ""
        for pattern in path_list:
            prompt_pattern = pattern
            # This works well for files, but not well for sub dir of a pattern.
            # If pattern is blank, then assume its repo-root (& it is included)
            if not pattern or file_name.match(pattern):
                break

            # Lastly, to support ignoring recursively with globs:
            # We know the file_name is not a directory, so
            # iterate through its parent paths and compare with the pattern
            file_parent = file_name.parent
            matched_parent = False
            while file_parent.parts:
                if file_parent.match(pattern):
                    matched_parent = True
                    break
                file_parent = file_parent.parent
            if matched_parent:
                break
        else:
            return False
        logger.debug(
            '"%s./%s" is %s as specified by pattern "%s"',
            tool_name,
            file_name.as_posix(),
            prompt,
            prompt_pattern or "./",
        )
        return True

    def is_source_or_ignored(self, file_name: str) -> bool:
        """Exclude undesired files (specified by user input :std:option:`--extensions`
        and :std:option:`--ignore` options).

        :param file_name: The name of file in question.

        :returns:
            ``True`` if (in order of precedence)

            - ``file_name`` is using one of the specified `extensions` AND
            - ``file_name`` is in `not_ignored` OR
            - ``file_name`` is not in `ignored`.

            Otherwise ``False``.
        """
        file_path = PurePath(file_name)
        return file_path.suffix.lstrip(".") in self.extensions and (
            self.is_file_in_list(ignored=False, file_name=file_path)
            or not self.is_file_in_list(ignored=True, file_name=file_path)
        )

    def list_source_files(self) -> List[FileObj]:
        """Make a list of source files to be checked.
        This will recursively walk the file tree collecting matches to
        anything that would return ``True`` from `is_source_or_ignored()`.

        :returns: A list of `FileObj` objects without diff information.
        """

        files = []
        for ext in self.extensions:
            for rel_path in Path(".").rglob(f"*.{ext}"):
                for parent in rel_path.parts[:-1]:
                    if parent.startswith("."):
                        break
                else:
                    file_path = rel_path.as_posix()
                    logger.debug('"./%s" is a source code file', file_path)
                    if self.is_source_or_ignored(rel_path.as_posix()):
                        files.append(FileObj(file_path))
        return files


class TidyFileFilter(FileFilter):
    """A specialized `FileFilter` whose debug prompts indicate clang-tidy preparation."""

    def __init__(
        self,
        ignore_value: str = "",
        extensions: Optional[List[str]] = None,
        not_ignored: Optional[List[str]] = None,
    ) -> None:
        super().__init__(
            ignore_value=ignore_value,
            extensions=extensions,
            not_ignored=not_ignored,
            tool_specific_name="clang-tidy",
        )


class FormatFileFilter(FileFilter):
    """A specialized `FileFilter` whose debug prompts indicate clang-format preparation."""

    def __init__(
        self,
        ignore_value: str = "",
        extensions: Optional[List[str]] = None,
        not_ignored: Optional[List[str]] = None,
    ) -> None:
        super().__init__(
            ignore_value=ignore_value,
            extensions=extensions,
            not_ignored=not_ignored,
            tool_specific_name="clang-format",
        )
