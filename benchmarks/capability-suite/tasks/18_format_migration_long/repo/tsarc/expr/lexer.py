"""Tokenizer for filter expressions."""
from dataclasses import dataclass

from ..errors import ExpressionError

KEYWORDS = {"and", "or", "not", "in", "between", "true", "false"}
TWO_CHAR = {"==", "!=", "<=", ">="}
ONE_CHAR = set("=<>~+-*/%(),")


@dataclass(frozen=True)
class Token:
    kind: str     # "num", "str", "ident", "kw", "op", "eof"
    value: object
    pos: int

    def is_op(self, *ops):
        return self.kind == "op" and self.value in ops

    def is_kw(self, *words):
        return self.kind == "kw" and self.value in words


def _read_number(text, i):
    start = i
    n = len(text)
    while i < n and text[i].isdigit():
        i += 1
    is_float = False
    if i < n and text[i] == "." and i + 1 < n and text[i + 1].isdigit():
        is_float = True
        i += 1
        while i < n and text[i].isdigit():
            i += 1
    if i < n and text[i] in "eE":
        j = i + 1
        if j < n and text[j] in "+-":
            j += 1
        if j < n and text[j].isdigit():
            is_float = True
            i = j
            while i < n and text[i].isdigit():
                i += 1
    raw = text[start:i]
    if i < n and (text[i].isalpha() or text[i] == "_"):
        raise ExpressionError(f"bad number {text[start:i + 1]!r}", start)
    return (float(raw) if is_float else int(raw)), i


def _read_string(text, i):
    quote = text[i]
    start = i
    i += 1
    out = []
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            nxt = text[i + 1]
            out.append({"n": "\n", "t": "\t", "\\": "\\", "'": "'", '"': '"'}.get(nxt, "\\" + nxt))
            i += 2
            continue
        if ch == quote:
            return "".join(out), i + 1
        out.append(ch)
        i += 1
    raise ExpressionError("unterminated string", start)


def tokenize(text):
    tokens = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and text[i + 1].isdigit()):
            if ch == ".":
                value, j = _read_number("0" + text[i:], 0)
                j = j - 1 + i
            else:
                value, j = _read_number(text, i)
            tokens.append(Token("num", value, i))
            i = j
            continue
        if ch in "'\"":
            value, j = _read_string(text, i)
            tokens.append(Token("str", value, i))
            i = j
            continue
        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (text[j].isalnum() or text[j] in "_."):
                j += 1
            word = text[i:j]
            if word.lower() in KEYWORDS:
                tokens.append(Token("kw", word.lower(), i))
            else:
                tokens.append(Token("ident", word, i))
            i = j
            continue
        if text[i:i + 2] in TWO_CHAR:
            tokens.append(Token("op", text[i:i + 2], i))
            i += 2
            continue
        if ch in ONE_CHAR:
            tokens.append(Token("op", ch, i))
            i += 1
            continue
        raise ExpressionError(f"unexpected character {ch!r}", i)
    tokens.append(Token("eof", None, n))
    return tokens
