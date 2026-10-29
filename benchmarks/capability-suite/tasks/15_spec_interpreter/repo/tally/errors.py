"""Tally exception classes (SPEC.md section 9). Do not change constructors or __str__."""


class TallyError(Exception):
    """Base class. `message` is the spec's message text, `line` is 1-based,
    `output` is everything the program printed before the error."""

    def __init__(self, message, line, output=""):
        super().__init__(message)
        self.message = message
        self.line = line
        self.output = output

    def __str__(self):
        return f"{self.message} (line {self.line})"


class TallySyntaxError(TallyError):
    def __init__(self, message, line, column, output=""):
        super().__init__(message, line, output)
        self.column = column

    def __str__(self):
        return f"{self.message} (line {self.line}, column {self.column})"


class TallyNameError(TallyError):
    pass


class TallyTypeError(TallyError):
    pass


class TallyZeroDivisionError(TallyError):
    pass


class TallyIndexError(TallyError):
    pass


class TallyRecursionError(TallyError):
    pass
