"""Tally: a small scripting language. See SPEC.md."""

from .errors import (
    TallyError, TallyIndexError, TallyNameError, TallyRecursionError,
    TallySyntaxError, TallyTypeError, TallyZeroDivisionError,
)
from .interp import run

__all__ = [
    "run", "TallyError", "TallySyntaxError", "TallyNameError", "TallyTypeError",
    "TallyZeroDivisionError", "TallyIndexError", "TallyRecursionError",
]
