"""``trellis explain QUERY``: show how a query was understood.

The output is three parts: the fully parenthesised canonical form, the
fields used with their types, and how many issues the query matches (when
the caller passes issues).  Useful when an ``and``/``or`` precedence
surprise makes a search return the wrong thing.
"""

from trellis.query import fields as F
from trellis.query.ast import fields_used, to_text
from trellis.query.parser import parse


def explain(text):
    tree = parse(text)
    used = fields_used(tree)
    lines = [f"query:  {to_text(tree) or '(everything)'}"]
    if used:
        lines.append("fields: " + ", ".join(f"{name} ({F.FIELDS[name].type})" for name in used))
    return lines


def field_reference():
    """One line per field: name, type, aliases, operators."""
    aliases = {}
    for alias, target in F.ALIASES.items():
        aliases.setdefault(target, []).append(alias)
    lines = []
    for name in sorted(F.FIELDS):
        field = F.FIELDS[name]
        ops = " ".join(F.operators_for(field)) if field.type != "bool" else "(bare) = !="
        extra = f" (also: {', '.join(sorted(aliases[name]))})" if name in aliases else ""
        lines.append(f"{name:<12} {field.type:<6} {ops}{extra}")
    return lines
