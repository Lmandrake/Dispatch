"""Tally interpreter (SPEC.md sections 1, 3-7, 9.2)."""


def run(source: str) -> str:
    """Parse and execute `source`; return everything it printed.

    On a runtime error, raise the matching Tally exception with `.output`
    set to what was printed before the error.
    """
    raise NotImplementedError
