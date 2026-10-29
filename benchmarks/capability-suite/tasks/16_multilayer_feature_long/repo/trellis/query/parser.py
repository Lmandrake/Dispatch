"""Recursive-descent parser for the query language.

Grammar (keywords are case-insensitive)::

    query      := or_expr EOF
    or_expr    := and_expr ( "or" and_expr )*
    and_expr   := unary ( "and"? unary )*        # juxtaposition means "and"
    unary      := "not" unary | primary
    primary    := "(" or_expr ")" | comparison
    comparison := FIELD OP value
                | FIELD "in" "(" value ( "," value )* ")"
                | FIELD                          # bool fields only
    value      := WORD | STRING

``and`` binds tighter than ``or``; ``not`` binds tightest.  An empty query
(only whitespace) matches everything and parses to None.  Field names are
resolved (aliases included) and operators checked against the field's type
here, so a parsed tree only ever names canonical fields.  Values are kept as
raw text; the compiler converts them.
"""

from trellis.errors import QueryError
from trellis.query import fields as F
from trellis.query.ast import And, Compare, Flag, Not, Or
from trellis.query.lexer import tokenize

KEYWORDS = ("and", "or", "not", "in")


class _Parser:
    def __init__(self, text):
        self.tokens = tokenize(text)
        self.i = 0

    @property
    def tok(self):
        return self.tokens[self.i]

    def peek(self, offset=1):
        j = min(self.i + offset, len(self.tokens) - 1)
        return self.tokens[j]

    def advance(self):
        tok = self.tokens[self.i]
        if tok.kind != "EOF":
            self.i += 1
        return tok

    def expect(self, kind, what):
        tok = self.tok
        if tok.kind != kind:
            raise QueryError(f"expected {what}, found {_show(tok)}", tok.pos)
        return self.advance()

    # ---- grammar ---------------------------------------------------------
    def parse(self):
        if self.tok.kind == "EOF":
            return None
        node = self.or_expr()
        if self.tok.kind != "EOF":
            raise QueryError(f"unexpected {_show(self.tok)}", self.tok.pos)
        return node

    def or_expr(self):
        node = self.and_expr()
        while self.tok.is_word("or"):
            self.advance()
            node = Or(node, self.and_expr())
        return node

    def and_expr(self):
        node = self.unary()
        while True:
            if self.tok.is_word("and"):
                self.advance()
                node = And(node, self.unary())
            elif self._starts_unary():
                node = And(node, self.unary())
            else:
                return node

    def _starts_unary(self):
        tok = self.tok
        if tok.kind == "LPAREN":
            return True
        return tok.kind == "WORD" and not tok.is_word("and", "or", "in")

    def unary(self):
        if self.tok.is_word("not"):
            self.advance()
            return Not(self.unary())
        return self.primary()

    def primary(self):
        tok = self.tok
        if tok.kind == "LPAREN":
            self.advance()
            node = self.or_expr()
            self.expect("RPAREN", "')'")
            return node
        if tok.kind != "WORD" or tok.is_word(*KEYWORDS):
            raise QueryError(f"expected a field name, found {_show(tok)}", tok.pos)
        return self.comparison()

    def comparison(self):
        name_tok = self.advance()
        field = F.lookup(name_tok.text, name_tok.pos)
        tok = self.tok
        if tok.is_word("in"):
            self.advance()
            F.check_operator(field, "in", tok.pos)
            self.expect("LPAREN", "'(' after in")
            values = [self.value()]
            while self.tok.kind == "COMMA":
                self.advance()
                values.append(self.value())
            self.expect("RPAREN", "')' to close the in-list")
            return Compare(field.name, "in", tuple(values), name_tok.pos)
        if tok.kind == "OP":
            self.advance()
            F.check_operator(field, tok.text, tok.pos)
            return Compare(field.name, tok.text, (self.value(),), name_tok.pos)
        if field.type == "bool":
            return Flag(field.name, name_tok.pos)
        raise QueryError(f"expected an operator after {name_tok.text!r}, found {_show(tok)}", tok.pos)

    def value(self):
        tok = self.tok
        if tok.kind == "STRING":
            self.advance()
            return tok.text
        if tok.kind == "WORD" and not tok.is_word("and", "or", "not"):
            self.advance()
            return tok.text
        raise QueryError(f"expected a value, found {_show(tok)}", tok.pos)


def _show(tok):
    if tok.kind == "EOF":
        return "end of query"
    if tok.kind == "STRING":
        return f"string {tok.text!r}"
    return repr(tok.text)


def parse(text):
    """Parse query text into a tree (None for an empty query)."""
    return _Parser(text or "").parse()
