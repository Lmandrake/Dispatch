"""Column value types.

tsarc knows five value types, named by short strings:

=========  ==================================================================
``ts``     timestamp: a Python ``int``, microseconds since the Unix epoch (i64)
``int``    signed 64-bit integer (``int``, never ``bool``)
``float``  IEEE-754 double (``float``; ints are accepted and converted)
``str``    text (``str``; must be encodable as UTF-8)
``bool``   ``True`` / ``False``
=========  ==================================================================
"""
import math
import struct

from .errors import SchemaError

TS = "ts"
INT = "int"
FLOAT = "float"
STR = "str"
BOOL = "bool"

ALL_TYPES = (TS, INT, FLOAT, STR, BOOL)
NUMERIC_TYPES = (TS, INT, FLOAT)

# On-disk type codes, shared by every format version.
TYPE_CODES = {TS: 1, INT: 2, FLOAT: 3, STR: 4, BOOL: 5}
CODE_TYPES = {code: name for name, code in TYPE_CODES.items()}

I64_MIN = -(2 ** 63)
I64_MAX = 2 ** 63 - 1

_F64 = struct.Struct("<d")
_U64 = struct.Struct("<Q")

_TRUE_WORDS = ("true", "t", "yes", "y", "1")
_FALSE_WORDS = ("false", "f", "no", "n", "0")


def check_type_name(name):
    if name not in ALL_TYPES:
        raise SchemaError(f"unknown column type {name!r} (expected one of {', '.join(ALL_TYPES)})")
    return name


def coerce(type_, value, what="value"):
    """Validate ``value`` for ``type_`` and return it in canonical form.

    Raises SchemaError when the value is not acceptable.
    """
    if type_ in (TS, INT):
        if isinstance(value, bool) or not isinstance(value, int):
            raise SchemaError(f"{what}: expected an int for type {type_}, got {type(value).__name__}")
        if not I64_MIN <= value <= I64_MAX:
            raise SchemaError(f"{what}: {value} does not fit in a signed 64-bit integer")
        return value
    if type_ == FLOAT:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SchemaError(f"{what}: expected a float, got {type(value).__name__}")
        try:
            return float(value)
        except OverflowError:
            raise SchemaError(f"{what}: {value} is too large for a float") from None
    if type_ == STR:
        if not isinstance(value, str):
            raise SchemaError(f"{what}: expected a str, got {type(value).__name__}")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise SchemaError(f"{what}: string is not encodable as UTF-8") from None
        return value
    if type_ == BOOL:
        if not isinstance(value, bool):
            raise SchemaError(f"{what}: expected a bool, got {type(value).__name__}")
        return value
    raise SchemaError(f"unknown column type {type_!r}")


def float_bits(value):
    """The 64-bit pattern of a float, as an unsigned int."""
    return _U64.unpack(_F64.pack(value))[0]


def float_from_bits(bits):
    return _F64.unpack(_U64.pack(bits))[0]


def values_equal(type_, a, b):
    """Exact equality: floats compare by bit pattern (so NaN == NaN and 0.0 != -0.0)."""
    if a is None or b is None:
        return a is None and b is None
    if type_ == FLOAT:
        return float_bits(a) == float_bits(b)
    return a == b


def sort_key(type_, value):
    """A key that orders values of one type; NaN sorts after every other float."""
    if type_ == FLOAT:
        return (1, 0.0) if math.isnan(value) else (0, value)
    return value


def parse_text(type_, text):
    """Parse the textual form of a value (as found in CSV files and filter expressions)."""
    from .timeutil import parse_ts

    if type_ == TS:
        return parse_ts(text)
    if type_ == INT:
        t = text.strip()
        try:
            v = int(t, 10)
        except ValueError:
            raise SchemaError(f"not an integer: {text!r}") from None
        return coerce(INT, v)
    if type_ == FLOAT:
        t = text.strip()
        try:
            return float(t)
        except ValueError:
            raise SchemaError(f"not a number: {text!r}") from None
    if type_ == STR:
        return text
    if type_ == BOOL:
        t = text.strip().lower()
        if t in _TRUE_WORDS:
            return True
        if t in _FALSE_WORDS:
            return False
        raise SchemaError(f"not a boolean: {text!r}")
    raise SchemaError(f"unknown column type {type_!r}")


def format_text(type_, value):
    """The canonical textual form of a value (inverse of :func:`parse_text`)."""
    from .timeutil import format_ts

    if type_ == TS:
        return format_ts(value)
    if type_ == INT:
        return str(value)
    if type_ == FLOAT:
        return repr(value)
    if type_ == STR:
        return value
    if type_ == BOOL:
        return "true" if value else "false"
    raise SchemaError(f"unknown column type {type_!r}")


def looks_like(type_, text):
    """True when ``text`` parses as ``type_`` (used by CSV type inference)."""
    try:
        parse_text(type_, text)
    except (SchemaError, ValueError):
        return False
    if type_ == BOOL:
        # digits are ints first; only words count as booleans for inference
        return text.strip().lower() in ("true", "false", "yes", "no")
    return True
