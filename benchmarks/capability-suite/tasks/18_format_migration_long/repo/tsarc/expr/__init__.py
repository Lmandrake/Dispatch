"""Filter expressions over archive rows.

Grammar (lowest precedence first)::

    expr     := or
    or       := and ("or" and)*
    and      := not ("and" not)*
    not      := "not" not | cmp
    cmp      := sum (("=" | "==" | "!=" | "<" | "<=" | ">" | ">=" | "~") sum)?
              | sum "in" "(" literal ("," literal)* ")"
              | sum "between" sum "and" sum
    sum      := product (("+" | "-") product)*
    product  := unary (("*" | "/" | "%") unary)*
    unary    := "-" unary | atom
    atom     := NUMBER | STRING | "true" | "false" | IDENT | IDENT "(" args ")" | "(" expr ")"

``~`` is a regular-expression search on text.  A string literal compared with
a ``ts`` column is parsed as a timestamp (``ts >= '2026-03-01'``).  See
docs/EXPRESSIONS.md for the functions.
"""
from .compiler import (CompiledExpression, CompiledValueExpression, compile_expression,
                       compile_value_expression)
from .lexer import Token, tokenize
from .parser import parse

__all__ = ["CompiledExpression", "CompiledValueExpression", "compile_expression",
           "compile_value_expression", "parse", "tokenize", "Token"]
