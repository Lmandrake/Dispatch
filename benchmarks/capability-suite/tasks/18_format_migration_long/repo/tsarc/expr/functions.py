"""Functions callable from filter expressions.

Each entry maps a lower-case name to ``(arity, result_type, impl, arg_types)``
where ``arg_types`` is a tuple of allowed type sets (``None`` = any type).
"""
import datetime as _dt
import math

from .. import types as T
from ..timeutil import US_PER_SECOND

_EPOCH = _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc)
NUM = {T.INT, T.FLOAT, T.TS}


def _moment(us):
    return _EPOCH + _dt.timedelta(microseconds=us)


def _abs(x):
    return abs(x)


def _len(s):
    return len(s)


def _lower(s):
    return s.lower()


def _upper(s):
    return s.upper()


def _startswith(s, p):
    return s.startswith(p)


def _endswith(s, p):
    return s.endswith(p)


def _contains(s, p):
    return p in s


def _isnan(x):
    return isinstance(x, float) and math.isnan(x)


def _round(x):
    return float(round(x))


def _hour(us):
    return _moment(us).hour


def _minute(us):
    return _moment(us).minute


def _second(us):
    return _moment(us).second


def _day(us):
    return _moment(us).day


def _month(us):
    return _moment(us).month


def _year(us):
    return _moment(us).year


def _weekday(us):
    """Monday = 0 ... Sunday = 6."""
    return _moment(us).weekday()


def _epoch_seconds(us):
    return us // US_PER_SECOND


FUNCTIONS = {
    "abs": (1, "same", _abs, ({T.INT, T.FLOAT},)),
    "len": (1, T.INT, _len, ({T.STR},)),
    "lower": (1, T.STR, _lower, ({T.STR},)),
    "upper": (1, T.STR, _upper, ({T.STR},)),
    "startswith": (2, T.BOOL, _startswith, ({T.STR}, {T.STR})),
    "endswith": (2, T.BOOL, _endswith, ({T.STR}, {T.STR})),
    "contains": (2, T.BOOL, _contains, ({T.STR}, {T.STR})),
    "isnan": (1, T.BOOL, _isnan, ({T.FLOAT, T.INT},)),
    "round": (1, T.FLOAT, _round, ({T.FLOAT, T.INT},)),
    "hour": (1, T.INT, _hour, ({T.TS},)),
    "minute": (1, T.INT, _minute, ({T.TS},)),
    "second": (1, T.INT, _second, ({T.TS},)),
    "day": (1, T.INT, _day, ({T.TS},)),
    "month": (1, T.INT, _month, ({T.TS},)),
    "year": (1, T.INT, _year, ({T.TS},)),
    "weekday": (1, T.INT, _weekday, ({T.TS},)),
    "epoch_seconds": (1, T.INT, _epoch_seconds, ({T.TS},)),
}
