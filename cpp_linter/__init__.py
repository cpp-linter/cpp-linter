"""The Base module of the :mod:`cpp_linter` package. This holds the objects shared by
multiple modules."""
import os
from pathlib import Path

# global constant variables
CACHE_PATH = Path(os.getenv("CPP_LINTER_CACHE", ".cpp-linter_cache"))
