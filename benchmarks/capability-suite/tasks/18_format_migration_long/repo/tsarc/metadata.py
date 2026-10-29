"""Archive metadata: a small ordered ``str -> str`` mapping stored in the header.

Keys are short identifiers (``source``, ``station.id``, ``units.temp`` ...);
values are free text.  Order is preserved exactly as given, which matters for
byte-exact output.
"""
import re

from .errors import SchemaError

KEY_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]{0,127}$")


def check_key(key):
    if not isinstance(key, str) or not KEY_RE.match(key):
        raise SchemaError(f"bad metadata key {key!r}: letters, digits, '_', '.', '-'; at most 128 "
                          f"characters, not starting with '.' or '-'")
    return key


def normalize(metadata):
    """Validate and copy a metadata mapping (``None`` -> ``{}``)."""
    if metadata is None:
        return {}
    if not isinstance(metadata, dict):
        metadata = dict(metadata)
    out = {}
    for key, value in metadata.items():
        check_key(key)
        if not isinstance(value, str):
            raise SchemaError(f"metadata value for {key!r} must be a str, got {type(value).__name__}")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise SchemaError(f"metadata value for {key!r} is not encodable as UTF-8") from None
        out[key] = value
    return out


def parse_assignment(text):
    """Parse ``key=value`` (the value may be empty and may contain ``=``)."""
    if "=" not in text:
        raise SchemaError(f"metadata must look like key=value, got {text!r}")
    key, value = text.split("=", 1)
    key = key.strip()
    check_key(key)
    return key, value


def updated(metadata, set_pairs=(), unset_keys=()):
    """A copy of ``metadata`` with keys set (appended at the end if new) and removed."""
    out = dict(metadata)
    for key, value in set_pairs:
        check_key(key)
        out[key] = value
    for key in unset_keys:
        if key not in out:
            raise SchemaError(f"no metadata key {key!r}")
        del out[key]
    return out


def format_lines(metadata):
    if not metadata:
        return ["metadata: -"]
    lines = ["metadata:"]
    for key, value in metadata.items():
        lines.append(f"  {key} = {value}")
    return lines
