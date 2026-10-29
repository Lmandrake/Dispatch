"""Canonical JSON encoding for payloads, results and WAL records.

taskmill stores job payloads and results as JSON values. They are encoded
canonically (sorted keys, no insignificant whitespace, UTF-8, no ASCII
escaping) so that equal values always produce equal bytes: the WAL CRCs, the
snapshot checksums and the payload size limits all depend on that.

Only plain JSON values are accepted: ``None``, ``bool``, ``int``, finite
``float``, ``str``, ``list``/``tuple`` and ``dict`` with ``str`` keys. NaN and
infinities are rejected (they are not JSON), as are sets, bytes and arbitrary
objects. Tuples come back as lists.
"""

import json
import math
from typing import Any

from .errors import ValidationError

_MAX_DEPTH = 64


def _check(value: Any, path: str, depth: int) -> None:
    if depth > _MAX_DEPTH:
        raise ValidationError(f"value nested deeper than {_MAX_DEPTH} levels at {path}")
    if value is None or isinstance(value, (bool, str)):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValidationError(f"non-finite number at {path}")
        return
    if isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            _check(item, f"{path}[{i}]", depth + 1)
        return
    if isinstance(value, dict):
        for k, item in value.items():
            if not isinstance(k, str):
                raise ValidationError(f"non-string key {k!r} at {path}")
            _check(item, f"{path}.{k}", depth + 1)
        return
    raise ValidationError(f"{type(value).__name__} is not JSON-serialisable (at {path})")


def validate_json(value: Any, what: str = "value") -> None:
    """Raise ValidationError unless ``value`` is a plain JSON value."""
    _check(value, what, 0)


def dumps(value: Any) -> str:
    """Canonical JSON text for ``value`` (which must already be valid)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def encode(value: Any) -> bytes:
    """Canonical UTF-8 bytes for ``value``."""
    return dumps(value).encode("utf-8")


def loads(text) -> Any:
    if isinstance(text, (bytes, bytearray)):
        text = bytes(text).decode("utf-8")
    return json.loads(text)


def encoded_size(value: Any) -> int:
    return len(encode(value))


def check_size(value: Any, limit: int, what: str, error=ValidationError) -> bytes:
    """Validate ``value`` and return its encoding; ``error`` if over ``limit`` bytes."""
    validate_json(value, what)
    data = encode(value)
    if limit is not None and len(data) > limit:
        raise error(f"{what} is {len(data)} bytes, limit is {limit}")
    return data


def roundtrip(value: Any) -> Any:
    """``value`` as it will look after being stored (tuples become lists)."""
    return loads(encode(value))


def copy_json(value: Any) -> Any:
    """Deep copy of a JSON value (cheaper than roundtrip for small values)."""
    if isinstance(value, dict):
        return {k: copy_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [copy_json(v) for v in value]
    return value
