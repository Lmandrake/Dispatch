"""Payload schemas per job kind: a small subset of JSON Schema.

A schema is a plain dict. Supported keywords:

``type``                 one of ``object array string integer number boolean null`` or a list of them
``enum``                 the value must equal one of the listed values
``required``             (objects) property names that must be present
``properties``           (objects) a schema per property name
``additionalProperties`` (objects) ``False`` rejects unlisted properties; a schema validates them
``items``                (arrays) a schema applied to every element
``minItems``/``maxItems``   (arrays) length bounds
``minimum``/``maximum``     (numbers) inclusive bounds
``minLength``/``maxLength`` (strings) length bounds in characters
``pattern``              (strings) a regular expression, searched anywhere in the value

Booleans are not numbers. Errors carry a JSON-pointer-like path such as
``/items/2/qty`` (``/`` is the whole payload). :func:`validate` returns every
error it finds; :func:`check` raises :class:`SchemaError` with all of them.

A :class:`SchemaRegistry` maps ``(queue, kind)`` to a schema, with a ``kind``-only
fallback, and :func:`validated_enqueue` refuses to enqueue a payload that does
not match the schema registered for its job.
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .errors import ConfigError, ValidationError

TYPES = ("object", "array", "string", "integer", "number", "boolean", "null")
KEYWORDS = frozenset({"type", "enum", "required", "properties", "additionalProperties", "items",
                      "minItems", "maxItems", "minimum", "maximum", "minLength", "maxLength", "pattern"})


@dataclass(frozen=True)
class SchemaIssue:
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


class SchemaError(ValidationError):
    """A payload does not match its schema; ``issues`` lists every violation."""

    def __init__(self, issues: List[SchemaIssue]):
        self.issues = list(issues)
        shown = "; ".join(str(i) for i in self.issues[:5])
        more = f" (+{len(self.issues) - 5} more)" if len(self.issues) > 5 else ""
        super().__init__(f"payload does not match schema: {shown}{more}")


def _is_type(value: Any, name: str) -> bool:
    if name == "null":
        return value is None
    if name == "boolean":
        return isinstance(value, bool)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "string":
        return isinstance(value, str)
    if name == "array":
        return isinstance(value, (list, tuple))
    return isinstance(value, dict)


def _type_name(value: Any) -> str:
    for name in ("null", "boolean", "integer", "number", "string", "array", "object"):
        if _is_type(value, name):
            return name
    return type(value).__name__


def _join(path: str, part: Any) -> str:
    escaped = str(part).replace("~", "~0").replace("/", "~1")
    return f"{path.rstrip('/')}/{escaped}"


def check_schema(schema: Any, path: str = "/") -> None:
    """Raise ConfigError when ``schema`` itself is malformed."""
    if not isinstance(schema, dict):
        raise ConfigError(f"schema at {path} must be an object")
    unknown = sorted(set(schema) - KEYWORDS)
    if unknown:
        raise ConfigError(f"schema at {path}: unknown keyword(s) {', '.join(unknown)}")
    types = schema.get("type")
    if types is not None:
        names = [types] if isinstance(types, str) else types
        if not isinstance(names, list) or not names or any(n not in TYPES for n in names):
            raise ConfigError(f"schema at {path}: type must be one or more of {', '.join(TYPES)}")
    if "enum" in schema and (not isinstance(schema["enum"], list) or not schema["enum"]):
        raise ConfigError(f"schema at {path}: enum must be a non-empty list")
    if "required" in schema and (not isinstance(schema["required"], list)
                                 or not all(isinstance(r, str) for r in schema["required"])):
        raise ConfigError(f"schema at {path}: required must be a list of names")
    if "pattern" in schema:
        try:
            re.compile(schema["pattern"])
        except (re.error, TypeError) as exc:
            raise ConfigError(f"schema at {path}: bad pattern ({exc})")
    for key in ("minItems", "maxItems", "minLength", "maxLength"):
        v = schema.get(key)
        if v is not None and (isinstance(v, bool) or not isinstance(v, int) or v < 0):
            raise ConfigError(f"schema at {path}: {key} must be a non-negative integer")
    for key in ("minimum", "maximum"):
        v = schema.get(key)
        if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))):
            raise ConfigError(f"schema at {path}: {key} must be a number")
    for name, sub in (schema.get("properties") or {}).items():
        check_schema(sub, _join(path, name))
    if "items" in schema:
        check_schema(schema["items"], _join(path, "items"))
    extra = schema.get("additionalProperties")
    if extra is not None and not isinstance(extra, bool):
        check_schema(extra, _join(path, "additionalProperties"))


def validate(value: Any, schema: dict, path: str = "/") -> List[SchemaIssue]:
    """Every violation of ``schema`` by ``value``, in document order."""
    issues: List[SchemaIssue] = []
    _walk(value, schema, path, issues)
    return issues


def check(value: Any, schema: dict) -> None:
    issues = validate(value, schema)
    if issues:
        raise SchemaError(issues)


def _walk(value: Any, schema: dict, path: str, out: List[SchemaIssue]) -> None:
    types = schema.get("type")
    if types is not None:
        names = [types] if isinstance(types, str) else types
        if not any(_is_type(value, n) for n in names):
            out.append(SchemaIssue(path, f"expected {' or '.join(names)}, got {_type_name(value)}"))
            return
    if "enum" in schema and value not in schema["enum"]:
        out.append(SchemaIssue(path, f"must be one of {schema['enum']!r}"))
    if isinstance(value, dict):
        _walk_object(value, schema, path, out)
    elif isinstance(value, (list, tuple)):
        _walk_array(value, schema, path, out)
    elif isinstance(value, str):
        _walk_string(value, schema, path, out)
    elif _is_type(value, "number"):
        _walk_number(value, schema, path, out)


def _walk_object(value: dict, schema: dict, path: str, out: List[SchemaIssue]) -> None:
    props = schema.get("properties") or {}
    for name in schema.get("required", ()):
        if name not in value:
            out.append(SchemaIssue(_join(path, name), "is required"))
    extra = schema.get("additionalProperties")
    for name in value:
        child = _join(path, name)
        if name in props:
            _walk(value[name], props[name], child, out)
        elif extra is False:
            out.append(SchemaIssue(child, "is not allowed"))
        elif isinstance(extra, dict):
            _walk(value[name], extra, child, out)


def _walk_array(value: list, schema: dict, path: str, out: List[SchemaIssue]) -> None:
    if "minItems" in schema and len(value) < schema["minItems"]:
        out.append(SchemaIssue(path, f"needs at least {schema['minItems']} item(s), has {len(value)}"))
    if "maxItems" in schema and len(value) > schema["maxItems"]:
        out.append(SchemaIssue(path, f"allows at most {schema['maxItems']} item(s), has {len(value)}"))
    if "items" in schema:
        for i, item in enumerate(value):
            _walk(item, schema["items"], _join(path, i), out)


def _walk_string(value: str, schema: dict, path: str, out: List[SchemaIssue]) -> None:
    if "minLength" in schema and len(value) < schema["minLength"]:
        out.append(SchemaIssue(path, f"shorter than {schema['minLength']} character(s)"))
    if "maxLength" in schema and len(value) > schema["maxLength"]:
        out.append(SchemaIssue(path, f"longer than {schema['maxLength']} character(s)"))
    if "pattern" in schema and not re.search(schema["pattern"], value):
        out.append(SchemaIssue(path, f"does not match pattern {schema['pattern']!r}"))


def _walk_number(value: Any, schema: dict, path: str, out: List[SchemaIssue]) -> None:
    if "minimum" in schema and value < schema["minimum"]:
        out.append(SchemaIssue(path, f"must be >= {schema['minimum']}"))
    if "maximum" in schema and value > schema["maximum"]:
        out.append(SchemaIssue(path, f"must be <= {schema['maximum']}"))


class SchemaRegistry:
    """Schemas by job kind, optionally specialised per queue."""

    def __init__(self, strict: bool = False):
        self.strict = strict
        self._schemas: Dict[Tuple[Optional[str], str], dict] = {}

    def register(self, kind: str, schema: dict, queue: Optional[str] = None) -> None:
        check_schema(schema)
        self._schemas[(queue, kind)] = schema

    def unregister(self, kind: str, queue: Optional[str] = None) -> bool:
        return self._schemas.pop((queue, kind), None) is not None

    def lookup(self, queue: str, kind: str) -> Optional[dict]:
        return self._schemas.get((queue, kind)) or self._schemas.get((None, kind))

    def kinds(self) -> List[str]:
        return sorted({kind for _, kind in self._schemas})

    def validate(self, queue: str, kind: str, payload: Any) -> List[SchemaIssue]:
        schema = self.lookup(queue, kind)
        if schema is None:
            if self.strict:
                return [SchemaIssue("/", f"no schema registered for kind {kind!r}")]
            return []
        return validate(payload, schema)

    def check(self, queue: str, kind: str, payload: Any) -> None:
        issues = self.validate(queue, kind, payload)
        if issues:
            raise SchemaError(issues)


def validated_enqueue(broker, registry: SchemaRegistry, queue: str, kind: str, payload: Any = None, **kw):
    """``broker.enqueue`` after checking ``payload`` against the registered schema."""
    registry.check(queue, kind, payload)
    return broker.enqueue(queue, kind, payload, **kw)
