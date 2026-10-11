"""A dedicated module for `ClangVersions` class (to avoid circular imports)."""


class ClangVersions:
    """Holds the versions of clang-tidy and clang-format."""

    def __init__(self) -> None:
        #: The version of clang-tidy, or None if clang-tidy is not used.
        self.tidy: str | None = None
        #: The version of clang-format, or None if clang-format is not used.
        self.format: str | None = None
