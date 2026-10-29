"""Small text helpers shared by the CLI, exports and the digest."""

import re
import textwrap

_MENTION = re.compile(r"(?<![\w@])@([a-z][a-z0-9_.]{1,31})")


def plural(n, word, plural_word=None):
    """``plural(1, "issue")`` -> ``"1 issue"``; ``plural(2, "issue")`` -> ``"2 issues"``."""
    if n == 1:
        return f"{n} {word}"
    return f"{n} {plural_word or word + 's'}"


def wrap(text, width=72, indent=""):
    """Wrap each paragraph of ``text`` separately, keeping blank lines."""
    out = []
    for para in text.split("\n\n"):
        para = " ".join(para.split())
        if not para:
            continue
        out.append(textwrap.fill(para, width=width, initial_indent=indent, subsequent_indent=indent))
    return "\n\n".join(out)


def mentions(text):
    """Usernames mentioned as ``@name`` in ``text``, in first-seen order,
    without duplicates.  A trailing ``.`` is not part of the name."""
    seen = []
    for m in _MENTION.finditer(text or ""):
        name = m.group(1).rstrip(".")
        if name not in seen:
            seen.append(name)
    return seen


def join_or_dash(values, sep=", "):
    values = list(values)
    return sep.join(values) if values else "-"


def oneline(text, width=60):
    text = " ".join((text or "").split())
    if len(text) <= width:
        return text
    return text[: width - 3] + "..."
