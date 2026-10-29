"""Unit conversion for value columns.

Archives may record the unit of a column in their metadata under
``units.<column>`` (for example ``units.temp = °C``).  :func:`convert_column`
rescales a float column and updates that metadata entry.

Supported conversions are affine maps ``y = a * x + b`` between units of the
same dimension.
"""
from .errors import QueryError
from .schema import Column

# unit -> (dimension, factor to the base unit, offset to the base unit)
_UNITS = {
    # temperature, base kelvin
    "K": ("temperature", 1.0, 0.0),
    "°C": ("temperature", 1.0, 273.15),
    "C": ("temperature", 1.0, 273.15),
    "°F": ("temperature", 5.0 / 9.0, 273.15 - 32.0 * 5.0 / 9.0),
    "F": ("temperature", 5.0 / 9.0, 273.15 - 32.0 * 5.0 / 9.0),
    # pressure, base pascal
    "Pa": ("pressure", 1.0, 0.0),
    "hPa": ("pressure", 100.0, 0.0),
    "kPa": ("pressure", 1000.0, 0.0),
    "bar": ("pressure", 100000.0, 0.0),
    "mbar": ("pressure", 100.0, 0.0),
    "inHg": ("pressure", 3386.389, 0.0),
    # speed, base m/s
    "m/s": ("speed", 1.0, 0.0),
    "km/h": ("speed", 1000.0 / 3600.0, 0.0),
    "kn": ("speed", 1852.0 / 3600.0, 0.0),
    "mph": ("speed", 1609.344 / 3600.0, 0.0),
    # length, base metre
    "m": ("length", 1.0, 0.0),
    "mm": ("length", 0.001, 0.0),
    "cm": ("length", 0.01, 0.0),
    "km": ("length", 1000.0, 0.0),
    "in": ("length", 0.0254, 0.0),
    "ft": ("length", 0.3048, 0.0),
    # ratio
    "1": ("ratio", 1.0, 0.0),
    "%": ("ratio", 0.01, 0.0),
}


def known_units():
    return sorted(_UNITS)


def dimension(unit):
    try:
        return _UNITS[unit][0]
    except KeyError:
        raise QueryError(f"unknown unit {unit!r}") from None


def converter(src, dst):
    """``(a, b)`` such that ``value_in_dst = a * value_in_src + b``."""
    if dimension(src) != dimension(dst):
        raise QueryError(f"cannot convert {src} ({dimension(src)}) to {dst} ({dimension(dst)})")
    _, fs, os_ = _UNITS[src]
    _, fd, od = _UNITS[dst]
    a = fs / fd
    b = (os_ - od) / fd
    return a, b


def convert_value(value, src, dst):
    a, b = converter(src, dst)
    return a * value + b


def unit_key(column):
    return f"units.{column}"


def convert_column(table, metadata, column, dst, src=None):
    """Return ``(table, metadata)`` with ``column`` converted to unit ``dst``.

    The source unit is ``src`` or, when omitted, the ``units.<column>`` metadata entry.
    The column must be ``float`` (an ``int`` column becomes ``float``).
    """
    col = table.schema.column(column)
    if col.type not in ("int", "float"):
        raise QueryError(f"unit conversion needs a numeric column, {column!r} is {col.type}")
    if src is None:
        src = metadata.get(unit_key(column))
        if src is None:
            raise QueryError(f"no unit recorded for column {column!r} (metadata {unit_key(column)})")
    a, b = converter(src, dst)
    values = [None if v is None else a * v + b for v in table.column_view(column)]
    cols = table.columns()
    cols[column] = values
    new_schema_cols = [Column(c.name, "float") if c.name == column else c for c in table.schema]
    from .schema import Schema
    from .table import Table

    out = Table(Schema(new_schema_cols), cols)
    meta = dict(metadata)
    meta[unit_key(column)] = dst
    return out, meta
