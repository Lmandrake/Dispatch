"""Tokenizer for the query language.

Token kinds:

* ``WORD``    a bare word: letters, digits and ``_ - . / $ :``.  Field names,
              keywords and unquoted values are all WORDs; the parser decides
              which is which from context.
* ``STRING``  a double- or single-quoted string; backslash escapes the
              quote character and the backslash itself.
* ``OP``      one of ``= != < <= > >= ~``
* ``LPAREN`` / ``RPAREN`` / ``COMMA``
* ``EOF``     end of input (always the last token)

Every token records the 0-based offset where it starts, for error messages.
"""

from dataclasses import dataclass

from stockroom.errors import QueryError

OPERATORS = ("!=", "<=", ">=", "=", "<", ">", "~")
_WORD_EXTRA = set("_-./$:")


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    pos: int

    def is_word(self, *words):
        """True for a WORD token equal (case-insensitively) to one of ``words``."""
        return self.kind == "WORD" and self.text.lower() in words


def _is_word_char(ch):
    return ch.isalnum() or ch in _WORD_EXTRA


def tokenize(text):
    tokens = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "(":
            tokens.append(Token("LPAREN", ch, i))
            i += 1
            continue
        if ch == ")":
            tokens.append(Token("RPAREN", ch, i))
            i += 1
            continue
        if ch == ",":
            tokens.append(Token("COMMA", ch, i))
            i += 1
            continue
        if ch in "\"'":
            start, quote = i, ch
            i += 1
            buf = []
            while True:
                if i >= n:
                    raise QueryError("unterminated string", start)
                c = text[i]
                if c == "\\" and i + 1 < n and text[i + 1] in (quote, "\\"):
                    buf.append(text[i + 1])
                    i += 2
                    continue
                if c == quote:
                    i += 1
                    break
                buf.append(c)
                i += 1
            tokens.append(Token("STRING", "".join(buf), start))
            continue
        op = next((o for o in OPERATORS if text.startswith(o, i)), None)
        if op is not None:
            tokens.append(Token("OP", op, i))
            i += len(op)
            continue
        if _is_word_char(ch):
            start = i
            while i < n and _is_word_char(text[i]):
                i += 1
            tokens.append(Token("WORD", text[start:i], start))
            continue
        raise QueryError(f"unexpected character {ch!r}", i)
    tokens.append(Token("EOF", "", n))
    return tokens
