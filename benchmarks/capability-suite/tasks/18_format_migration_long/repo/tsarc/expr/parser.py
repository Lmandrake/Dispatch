"""Recursive-descent parser for filter expressions (grammar in tsarc.expr)."""
from ..errors import ExpressionError
from . import ast as A
from .lexer import tokenize

COMPARE_OPS = ("=", "==", "!=", "<", "<=", ">", ">=", "~")


class _Parser:
    def __init__(self, text):
        self.text = text
        self.tokens = tokenize(text)
        self.i = 0

    @property
    def tok(self):
        return self.tokens[self.i]

    def advance(self):
        t = self.tokens[self.i]
        self.i += 1
        return t

    def expect_op(self, op):
        t = self.tok
        if not t.is_op(op):
            raise ExpressionError(f"expected {op!r}", t.pos)
        return self.advance()

    def parse(self):
        if self.tok.kind == "eof":
            raise ExpressionError("empty expression", 0)
        node = self.parse_or()
        if self.tok.kind != "eof":
            raise ExpressionError(f"unexpected {self._describe(self.tok)}", self.tok.pos)
        return node

    def _describe(self, t):
        if t.kind == "eof":
            return "end of expression"
        if t.kind == "str":
            return f"string {t.value!r}"
        return repr(str(t.value))

    def parse_or(self):
        first = self.parse_and()
        operands = [first]
        while self.tok.is_kw("or"):
            self.advance()
            operands.append(self.parse_and())
        if len(operands) == 1:
            return first
        return A.BoolOp("or", tuple(operands), first.pos)

    def parse_and(self):
        first = self.parse_not()
        operands = [first]
        while self.tok.is_kw("and"):
            self.advance()
            operands.append(self.parse_not())
        if len(operands) == 1:
            return first
        return A.BoolOp("and", tuple(operands), first.pos)

    def parse_not(self):
        if self.tok.is_kw("not"):
            t = self.advance()
            return A.Not(self.parse_not(), t.pos)
        return self.parse_cmp()

    def parse_cmp(self):
        left = self.parse_sum()
        t = self.tok
        if t.kind == "op" and t.value in COMPARE_OPS:
            self.advance()
            right = self.parse_sum()
            op = "=" if t.value == "==" else t.value
            return A.Compare(op, left, right, t.pos)
        if t.is_kw("in"):
            self.advance()
            self.expect_op("(")
            items = [self.parse_literal()]
            while self.tok.is_op(","):
                self.advance()
                items.append(self.parse_literal())
            self.expect_op(")")
            return A.InList(left, tuple(items), t.pos)
        if t.is_kw("between"):
            self.advance()
            low = self.parse_sum()
            if not self.tok.is_kw("and"):
                raise ExpressionError("expected 'and' in between", self.tok.pos)
            self.advance()
            high = self.parse_sum()
            return A.Between(left, low, high, t.pos)
        return left

    def parse_literal(self):
        t = self.tok
        neg = False
        if t.is_op("-"):
            neg = True
            self.advance()
            t = self.tok
        if t.kind == "num":
            self.advance()
            return A.Literal(-t.value if neg else t.value, t.pos)
        if neg:
            raise ExpressionError("expected a number after '-'", t.pos)
        if t.kind == "str":
            self.advance()
            return A.Literal(t.value, t.pos)
        if t.is_kw("true", "false"):
            self.advance()
            return A.Literal(t.value == "true", t.pos)
        raise ExpressionError(f"expected a literal, found {self._describe(t)}", t.pos)

    def parse_sum(self):
        node = self.parse_product()
        while self.tok.is_op("+", "-"):
            t = self.advance()
            node = A.Binary(t.value, node, self.parse_product(), t.pos)
        return node

    def parse_product(self):
        node = self.parse_unary()
        while self.tok.is_op("*", "/", "%"):
            t = self.advance()
            node = A.Binary(t.value, node, self.parse_unary(), t.pos)
        return node

    def parse_unary(self):
        if self.tok.is_op("-"):
            t = self.advance()
            operand = self.parse_unary()
            if isinstance(operand, A.Literal) and isinstance(operand.value, (int, float)) \
                    and not isinstance(operand.value, bool):
                return A.Literal(-operand.value, t.pos)
            return A.Unary("-", operand, t.pos)
        return self.parse_atom()

    def parse_atom(self):
        t = self.tok
        if t.kind in ("num", "str"):
            self.advance()
            return A.Literal(t.value, t.pos)
        if t.is_kw("true", "false"):
            self.advance()
            return A.Literal(t.value == "true", t.pos)
        if t.kind == "ident":
            self.advance()
            if self.tok.is_op("("):
                self.advance()
                args = []
                if not self.tok.is_op(")"):
                    args.append(self.parse_or())
                    while self.tok.is_op(","):
                        self.advance()
                        args.append(self.parse_or())
                self.expect_op(")")
                return A.Call(t.value.lower(), tuple(args), t.pos)
            return A.Name(t.value, t.pos)
        if t.is_op("("):
            self.advance()
            node = self.parse_or()
            self.expect_op(")")
            return node
        raise ExpressionError(f"unexpected {self._describe(t)}", t.pos)


def parse(text):
    """Parse ``text`` into an AST (see :mod:`tsarc.expr.ast`)."""
    if not isinstance(text, str):
        raise ExpressionError("expression must be a string")
    return _Parser(text).parse()
