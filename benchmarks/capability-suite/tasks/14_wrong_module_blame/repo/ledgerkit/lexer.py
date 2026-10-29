"""Split ledger text into logical lines and fields.

Line kinds:

* blank lines and lines whose first non-space character is ``;`` are ignored;
* lines starting with ``!`` are directives, split on whitespace (double quotes
  group words, as in a shell);
* every other line is an entry, split on ``|``.

Inside an entry field a backslash escapes the next character (``\\|`` is a
literal bar, ``\\\\`` a backslash, ``\\"`` a quote).  A field may also be
wrapped in double quotes, in which case bars inside it are literal.  Leading
and trailing whitespace of every field is stripped (but not whitespace inside
quotes).  A line ending in a single backslash continues on the next line.
"""

from dataclasses import dataclass

from .errors import LexError

DELIM = "|"
COMMENT = ";"
DIRECTIVE = "!"


@dataclass(frozen=True)
class Line:
    number: int          # 1-based number of the first physical line
    kind: str            # "entry" or "directive"
    fields: tuple
    text: str


def logical_lines(text):
    """Yield (first_line_number, joined_text) pairs, honouring continuations."""
    buf = []
    start = None
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip("\r")
        if start is None:
            start = number
        if _ends_with_continuation(line):
            buf.append(line[:-1])
            continue
        buf.append(line)
        yield start, "".join(buf)
        buf = []
        start = None
    if buf:
        raise LexError("file ends inside a continued line", line=start)


def _ends_with_continuation(line):
    count = 0
    i = len(line) - 1
    while i >= 0 and line[i] == "\\":
        count += 1
        i -= 1
    return count % 2 == 1


def split_entry(text, *, line=None, source=None):
    """Split one entry line into stripped fields."""
    fields = []
    cur = []
    quoted_field = False
    in_quotes = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\":
            if i + 1 >= n:
                raise LexError("dangling escape", line=line, source=source)
            cur.append(text[i + 1])
            i += 2
            continue
        if ch == '"':
            if in_quotes:
                in_quotes = False
                rest = text[i + 1:]
                nxt = rest.lstrip(" \t")
                if nxt and nxt[0] != DELIM:
                    raise LexError("text after closing quote", line=line, source=source)
                i += 1 + (len(rest) - len(nxt))
                continue
            if "".join(cur).strip() == "":
                in_quotes = True
                quoted_field = True
                cur = []
                i += 1
                continue
            raise LexError("quote inside unquoted field", line=line, source=source)
        if ch == DELIM and not in_quotes:
            fields.append(_finish(cur, quoted_field))
            cur = []
            quoted_field = False
            i += 1
            continue
        cur.append(ch)
        i += 1
    if in_quotes:
        raise LexError("unterminated quote", line=line, source=source)
    fields.append(_finish(cur, quoted_field))
    return fields


def _finish(chars, quoted):
    s = "".join(chars)
    return s if quoted else s.strip()


def split_directive(text, *, line=None, source=None):
    """Split a directive line (without its leading ``!``) on whitespace."""
    words = []
    cur = []
    in_quotes = False
    have = False
    for ch in text:
        if in_quotes:
            if ch == '"':
                in_quotes = False
            else:
                cur.append(ch)
            continue
        if ch == '"':
            in_quotes = True
            have = True
            continue
        if ch.isspace():
            if cur or have:
                words.append("".join(cur))
                cur = []
                have = False
            continue
        cur.append(ch)
    if in_quotes:
        raise LexError("unterminated quote in directive", line=line, source=source)
    if cur or have:
        words.append("".join(cur))
    return words


def tokenize(text, *, source="<memory>"):
    """Yield Line records for every entry and directive in ``text``."""
    for number, joined in logical_lines(text):
        stripped = joined.strip()
        if not stripped or stripped.startswith(COMMENT):
            continue
        if stripped.startswith(DIRECTIVE):
            words = split_directive(stripped[1:], line=number, source=source)
            if not words:
                raise LexError("empty directive", line=number, source=source)
            yield Line(number, "directive", tuple(words), joined)
        else:
            fields = split_entry(stripped, line=number, source=source)
            yield Line(number, "entry", tuple(fields), joined)
