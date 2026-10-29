import os
import subprocess
import sys

import pytest

import tally
from tally import (
    TallyError, TallyIndexError, TallyNameError, TallyRecursionError,
    TallySyntaxError, TallyTypeError, TallyZeroDivisionError, run,
)


def p(expr):
    """Output of printing one expression, without the newline."""
    out = run(f"print({expr});")
    assert out.endswith("\n")
    return out[:-1]


def err(src, cls):
    with pytest.raises(cls) as ei:
        run(src)
    assert type(ei.value) is cls
    return ei.value


# ---------------------------------------------------------------- visible basics

def test_visible_basics():
    assert run("print(1 + 2);") == "3\n"
    assert run('print("a", 1, true, nil);') == "a 1 true nil\n"
    assert run("let x = 1; x = x + 41; print(x);") == "42\n"
    assert run("if 1 > 2 { print(1); } else { print(2); }") == "2\n"
    assert run("let i = 0; while i < 3 { print(i); i = i + 1; }") == "0\n1\n2\n"
    assert run("fn sq(x) { return x * x; } print(sq(7));") == "49\n"
    assert run('print([1, "two", [3]]);') == '[1, "two", [3]]\n'


def test_run_returns_empty_for_no_output():
    assert run("") == ""
    assert run("let x = 1;  # just a comment\n") == ""


def test_run_calls_are_independent():
    run("let x = 1; print(x);")
    assert run("let x = 2; print(x);") == "2\n"


def test_exports():
    for name in ("TallyError", "TallySyntaxError", "TallyNameError", "TallyTypeError",
                 "TallyZeroDivisionError", "TallyIndexError", "TallyRecursionError"):
        assert issubclass(getattr(tally, name), TallyError)


# ---------------------------------------------------------------- numbers

@pytest.mark.parametrize("expr,out", [
    ("123456789012345678901234567890 * 10", "1234567890123456789012345678900"),
    ("2 ** 100", "1267650600228229401496703205376"),
    ("007 + 1", "8"),
    ("1 / 3", "1/3"),
    ("-7 / 6", "-7/6"),
    ("1 / 8", "0.125"),
    ("-5 / 2", "-2.5"),
    ("1 / 20", "0.05"),
    ("6 / 3", "2"),
    ("0.1 + 0.2", "0.3"),
    ("2.50", "2.5"),
    ("2.0", "2"),
    ("3 * (1 / 3)", "1"),
    ("1 / 3 + 1 / 6", "0.5"),
    ("10 / 4 * 2", "5"),
    ("0.001", "0.001"),
    ("-0.5", "-0.5"),
    ("1 / 7 * 7.5", "15/14"),
])
def test_number_display(expr, out):
    assert p(expr) == out


@pytest.mark.parametrize("expr,out", [
    ("-7 // 2", "-4"),
    ("7 // -2", "-4"),
    ("7 // 2", "3"),
    ("7.5 // 2", "3"),
    ("-7.5 // 2", "-4"),
    ("-7 % 3", "2"),
    ("7 % -3", "-2"),
    ("7.5 % 2", "1.5"),
    ("-1 % 5", "4"),
    ("6 % 3", "0"),
    ("1 / 3 % 1 / 4", "1/12"),
])
def test_floor_div_and_mod(expr, out):
    assert p(expr) == out


@pytest.mark.parametrize("expr,out", [
    ("type(1.0)", "int"),
    ("type(6 / 3)", "int"),
    ("type(1 / 3)", "rat"),
    ("type(7.5 // 2)", "int"),
    ("type(\"\")", "str"),
    ("type(true)", "bool"),
    ("type(nil)", "nil"),
    ("type([])", "list"),
    ("type(len)", "function"),
    ("type(fn () {})", "function"),
])
def test_types(expr, out):
    assert p(expr) == out


@pytest.mark.parametrize("expr,out", [
    ("2 ** 10", "1024"),
    ("0 ** 0", "1"),
    ("2 ** -1", "0.5"),
    ("2 ** -2", "0.25"),
    ("3 ** -1", "1/3"),
    ("(1 / 2) ** 3", "0.125"),
    ("(-2) ** 3", "-8"),
    ("(2 / 3) ** -2", "2.25"),
])
def test_power(expr, out):
    assert p(expr) == out


@pytest.mark.parametrize("src,msg", [
    ("print(1 / 0);", "division by zero"),
    ("print(1 // 0);", "division by zero"),
    ("print(1 % 0);", "division by zero"),
    ("print(1 / (1 - 1.0));", "division by zero"),
    ("print(0 ** -1);", "division by zero"),
])
def test_zero_division(src, msg):
    e = err(src, TallyZeroDivisionError)
    assert e.message == msg and e.line == 1


def test_rat_exponent_is_type_error():
    e = err("print(4 ** 0.5);", TallyTypeError)
    assert e.message == "exponent must be an int"


# ---------------------------------------------------------------- precedence

@pytest.mark.parametrize("expr,out", [
    ("-2 ** 2", "-4"),
    ("(-2) ** 2", "4"),
    ("2 ** 3 ** 2", "512"),
    ("2 ** -2 ** 2", "0.0625"),
    ("--3", "3"),
    ("-3 - -3", "0"),
    ("1 + 2 * 3", "7"),
    ("(1 + 2) * 3", "9"),
    ("10 - 4 - 3", "3"),
    ("100 / 10 / 5", "2"),
    ("2 * 3 ** 2", "18"),
    ("-2 ** 2 * 3", "-12"),
    ("not 1 == 2", "true"),
    ("not 0 and 5", "5"),
    ("1 or 2 and 0", "1"),
    ("[1, 2, 3][1] ** 2", "4"),
    ("-[5][0]", "-5"),
])
def test_precedence(expr, out):
    assert p(expr) == out


# ---------------------------------------------------------------- strings

def test_string_escapes():
    assert run(r'print("a\tb\\c\"d");') == 'a\tb\\c"d\n'
    assert run(r'print("x\ny");') == "x\ny\n"
    assert run(r'print("\u{41}\u{e9}\u{1F600}\u{0}!");') == "A\u00e9\U0001F600\x00!\n"
    assert p(r'len("\u{10FFFF}")') == "1"


def test_string_ops():
    assert p('"ab" + "cd"') == "abcd"
    assert p('"ab" * 3') == "ababab"
    assert p('2 * "xy"') == "xyxy"
    assert p('"ab" * -1 + "|"') == "|"
    assert p(r'len("h\u{e9}llo")') == "5"
    assert p('"hello"[1]') == "e"
    assert p('"hello"[-1]') == "o"
    assert p('"hello"[1:3]') == "el"
    assert p('"abc" < "abd"') == "true"
    assert p('"Z" < "a"') == "true"
    assert p('"ab" < "abc"') == "true"
    assert p('"b" >= "abc"') == "true"


@pytest.mark.parametrize("src,msg,line,col", [
    ('print("abc);', "unterminated string", 1, 7),
    ('let s =\n  "abc\n";', "unterminated string", 2, 3),
    ('print("a\\qb");', "invalid escape sequence '\\q'", 1, 9),
    ('print(\n"ok", "a\\u{110000}");', "invalid unicode escape", 2, 9),
    ('print("\\u41");', "invalid unicode escape", 1, 8),
    ('print("\\u{}");', "invalid unicode escape", 1, 8),
    ('print("\\u{1234567}");', "invalid unicode escape", 1, 8),
    ('print("\\u{12g}");', "invalid unicode escape", 1, 8),
    ('print("a\\q', "invalid escape sequence '\\q'", 1, 9),
    ('print("abc\\', "unterminated string", 1, 7),
])
def test_string_lex_errors(src, msg, line, col):
    e = err(src, TallySyntaxError)
    assert (e.message, e.line, e.column) == (msg, line, col)


# ---------------------------------------------------------------- display form

def test_display_nested():
    assert p('[1, "a\\"b", "c\\\\d", "e\\nf", "g\\th", [], [[nil]], 1/2, false]') == \
        '[1, "a\\"b", "c\\\\d", "e\\nf", "g\\th", [], [[nil]], 0.5, false]'
    assert p(r'["\u{e9}"]') == '["\u00e9"]'
    assert p('str([1, "x"])') == '[1, "x"]'
    assert p('str("plain") + "!"') == "plain!"
    assert p('str(1/3)') == "1/3"
    assert p('type(str(5))') == "str"


def test_display_functions():
    src = """
    fn named() {}
    let anon = fn () {};
    print(named, anon, print, range, [named, len]);
    print(str(fn (x) { return x; }));
    """
    assert run(src) == "<fn named> <fn> <builtin print> <builtin range> [<fn named>, <builtin len>]\n<fn>\n"


def test_display_self_containing_list():
    assert run("let a = [1]; push(a, a); print(a);") == "[1, [...]]\n"
    assert run("let a = [1]; let b = [a]; push(a, b); print(a); print(b);") == \
        "[1, [[...]]]\n[[1, [...]]]\n"
    # the same list appearing twice side by side is not a cycle
    assert run("let a = [1]; print([a, a]);") == "[[1], [1]]\n"


def test_print_forms():
    assert run("print();") == "\n"
    assert run('print("a", "b");') == "a b\n"
    assert run('print(["a"], "a");') == '["a"] a\n'
    assert p("print(1) == nil") == "1\ntrue"


# ---------------------------------------------------------------- comparisons and logic

@pytest.mark.parametrize("expr,out", [
    ("1 < 2 < 3", "true"),
    ("3 > 2 > 1", "true"),
    ("1 < 3 < 2", "false"),
    ("1 < 2 == true", "false"),
    ("1 == 1 == 1", "true"),
    ("1 < 2 <= 2 != 3", "true"),
    ("1 == 1.0", "true"),
    ("1 / 2 == 0.5", "true"),
    ("true == 1", "false"),
    ("nil == false", "false"),
    ("0 == false", "false"),
    ('"1" == 1', "false"),
    ("[1, [2, 3]] == [1, [2, 3.0]]", "true"),
    ("[1, 2] == [1, 2, 3]", "false"),
    ("[] != []", "false"),
    ("len == len", "true"),
    ("fn () {} == fn () {}", "false"),
    ("nil == nil", "true"),
])
def test_comparisons(expr, out):
    assert p(expr) == out


def test_comparison_chain_evaluates_middle_once_and_short_circuits():
    src = """
    let n = 0;
    fn mid() { n = n + 1; return 5; }
    fn boom() { print("boom"); return 0; }
    print(1 < mid() < 10);
    print(n);
    print(3 < 2 < boom());
    print(1 < 2 > 3 < boom());
    """
    assert run(src) == "true\n1\nfalse\nfalse\n"


def test_function_equality_identity():
    assert run("fn f() {} let g = f; print(g == f, [f] == [g]);") == "true true\n"


@pytest.mark.parametrize("expr,out", [
    ("nil or 5", "5"),
    ("0 and 1", "0"),
    ('"" or "x"', "x"),
    ("[] or [0]", "[0]"),
    ('2 and "y"', "y"),
    ("false or nil", "nil"),
    ("1 or 2", "1"),
    ("not []", "true"),
    ("not [0]", "false"),
    ("not 0.0", "true"),
    ('not ""', "true"),
    ('not " "', "false"),
    ("not len", "false"),
    ("not nil", "true"),
])
def test_logic_values(expr, out):
    assert p(expr) == out


def test_short_circuit_skips_side_effects():
    src = """
    fn side(v) { print("side", v); return v; }
    let a = side(0) and side(1);
    let b = side(2) or side(3);
    print(a, b);
    """
    assert run(src) == "side 0\nside 2\n0 2\n"


def test_truthiness_in_conditions():
    src = """
    let vals = [0, 1, "", "a", [], [nil], nil, false, true, 1/2, fn () {}];
    let i = 0;
    let s = "";
    while i < len(vals) {
      if vals[i] { s = s + "T"; } else { s = s + "F"; }
      i = i + 1;
    }
    print(s);
    """
    assert run(src) == "FTFTFTFFTTT\n"


# ---------------------------------------------------------------- lists, indexing, slicing

@pytest.mark.parametrize("expr,out", [
    ("[1, 2, 3][-1]", "3"),
    ("[1, 2, 3][-3]", "1"),
    ("[1, 2, 3, 4, 5][1:3]", "[2, 3]"),
    ("[1, 2, 3, 4, 5][-2:]", "[4, 5]"),
    ("[1, 2, 3, 4, 5][:-3]", "[1, 2]"),
    ("[1, 2, 3][:]", "[1, 2, 3]"),
    ("[1, 2, 3][2:1]", "[]"),
    ("[1, 2, 3][-100:100]", "[1, 2, 3]"),
    ("[1, 2, 3][5:]", "[]"),
    ('"hello"[-3:]', "llo"),
    ('"hello"[10:]', ""),
    ('type("hello"[3:1])', "str"),
    ("[1, 2] + [3]", "[1, 2, 3]"),
    ("[0] * 3", "[0, 0, 0]"),
    ("2 * [1, 2]", "[1, 2, 1, 2]"),
    ("[1] * 0", "[]"),
    ("[1, 2, 3,]", "[1, 2, 3]"),
    ("len([[1, 2], 3])", "2"),
    ("range(4)", "[0, 1, 2, 3]"),
    ("range(2, 5)", "[2, 3, 4]"),
    ("range(5, 2)", "[]"),
    ("range(-2)", "[]"),
    ("range(-2, 1)", "[-2, -1, 0]"),
])
def test_list_exprs(expr, out):
    assert p(expr) == out


def test_list_mutation_and_aliasing():
    src = """
    let a = [1, 2, 3];
    let b = a;
    b[0] = 10;
    a[-1] = "z";
    push(b, [4]);
    print(a);
    let c = a[:];
    c[0] = 0;
    print(a[0], c[0]);
    let d = a + [];
    push(d, 5);
    print(len(a), len(d));
    let m = [[0, 0], [0, 0]];
    m[1][0] = 7;
    print(m);
    """
    assert run(src) == '[10, 2, "z", [4]]\n10 0\n4 5\n[[0, 0], [7, 0]]\n'


def test_repeat_makes_new_list():
    assert run("let a = [1]; let b = a * 1; push(b, 2); print(a, b);") == "[1] [1, 2]\n"


@pytest.mark.parametrize("src,cls,msg", [
    ("print([1, 2][2]);", TallyIndexError, "list index out of range"),
    ("print([1, 2][-3]);", TallyIndexError, "list index out of range"),
    ("print([][0]);", TallyIndexError, "list index out of range"),
    ('print("ab"[2]);', TallyIndexError, "string index out of range"),
    ("let a = [1]; a[1] = 2;", TallyIndexError, "list assignment index out of range"),
    ("let a = [1]; a[-2] = 2;", TallyIndexError, "list assignment index out of range"),
    ("print([1, 2][0.5]);", TallyTypeError, "indices must be int, not 'rat'"),
    ('print([1, 2]["0"]);', TallyTypeError, "indices must be int, not 'str'"),
    ("print([1, 2][true]);", TallyTypeError, "indices must be int, not 'bool'"),
    ("print([1, 2][nil:]);", TallyTypeError, "indices must be int, not 'nil'"),
    ("print([1, 2][:1/2]);", TallyTypeError, "indices must be int, not 'rat'"),
    ("print(5[0]);", TallyTypeError, "'int' is not indexable"),
    ("print(nil[0:1]);", TallyTypeError, "'nil' is not indexable"),
    ("print(5[true]);", TallyTypeError, "'int' is not indexable"),
    ('let s = "ab"; s[0] = "x";', TallyTypeError, "'str' does not support item assignment"),
    ("let n = 3; n[0] = 1;", TallyTypeError, "'int' does not support item assignment"),
    ("let a = [1]; a[\"0\"] = 2;", TallyTypeError, "indices must be int, not 'str'"),
    ("let n = nil; n[9.5] = 1;", TallyTypeError, "'nil' does not support item assignment"),
    ("let a = [1]; a[1.5] = 2;", TallyTypeError, "indices must be int, not 'rat'"),
])
def test_index_errors(src, cls, msg):
    e = err(src, cls)
    assert e.message == msg and e.line == 1


def test_setitem_evaluation_order():
    src = """
    fn t(tag, v) { print(tag); return v; }
    t("x", [0])[t("i", 0)] = t("v", 1);
    t("x", 5)[t("i", 0)] = t("v", 1);
    """
    e = err(src, TallyTypeError)
    assert e.output == "x\ni\nv\nx\ni\nv\n"
    assert e.message == "'int' does not support item assignment"
    assert e.line == 4


# ---------------------------------------------------------------- operator type errors

@pytest.mark.parametrize("src,msg", [
    ("print(1 + \"a\");", "unsupported operand types for +: 'int' and 'str'"),
    ("print(\"a\" - \"b\");", "unsupported operand types for -: 'str' and 'str'"),
    ("print(true + 1);", "unsupported operand types for +: 'bool' and 'int'"),
    ("print([1] + 1);", "unsupported operand types for +: 'list' and 'int'"),
    ("print(\"a\" * 1.5);", "unsupported operand types for *: 'str' and 'rat'"),
    ("print(\"a\" * \"b\");", "unsupported operand types for *: 'str' and 'str'"),
    ("print([1] * true);", "unsupported operand types for *: 'list' and 'bool'"),
    ("print(nil // 2);", "unsupported operand types for //: 'nil' and 'int'"),
    ("print(1 % [1]);", "unsupported operand types for %: 'int' and 'list'"),
    ("print(\"2\" ** 2);", "unsupported operand types for **: 'str' and 'int'"),
    ("print(2 ** \"2\");", "unsupported operand types for **: 'int' and 'str'"),
    ("print(2 / nil);", "unsupported operand types for /: 'int' and 'nil'"),
    ("print(len / 1);", "unsupported operand types for /: 'function' and 'int'"),
    ("print(-\"a\");", "bad operand type for unary -: 'str'"),
    ("print(-true);", "bad operand type for unary -: 'bool'"),
    ("print(1 < \"a\");", "'<' not supported between 'int' and 'str'"),
    ("print([1] <= [2]);", "'<=' not supported between 'list' and 'list'"),
    ("print(nil > nil);", "'>' not supported between 'nil' and 'nil'"),
    ("print(1 < 2 >= true);", "'>=' not supported between 'int' and 'bool'"),
])
def test_operator_type_errors(src, msg):
    e = err(src, TallyTypeError)
    assert e.message == msg and e.line == 1


def test_operator_error_line_is_operator_line():
    e = err('let x = 1\n  +\n  "a";', TallyTypeError)
    assert e.line == 2
    e = err("let x =\n  -\n\n  nil;", TallyTypeError)
    assert e.line == 2
    e = err("print(1 <\n 2 <\n \"x\");", TallyTypeError)
    assert e.line == 2
    e = err("print(10\n//\n0);", TallyZeroDivisionError)
    assert e.line == 2


def test_operands_evaluated_before_type_check():
    e = err('fn t(v) { print(v); return v; }\nprint(t(1) + t("a"));', TallyTypeError)
    assert e.output == "1\na\n"


# ---------------------------------------------------------------- scoping

def test_block_scope_and_shadowing():
    src = """
    let x = 1;
    if true {
      let x = 2;
      print(x);
      x = 3;
      print(x);
    }
    print(x);
    if true { x = 4; }
    print(x);
    """
    assert run(src) == "2\n3\n1\n4\n"


def test_let_initializer_sees_outer_binding():
    assert run("let x = 10; if true { let x = x + 1; print(x); } print(x);") == "11\n10\n"


def test_let_without_initializer_is_nil():
    assert run("let x; print(x);") == "nil\n"


def test_redeclaration_same_scope():
    e = err("let a = 1;\nlet a = 2;", TallyNameError)
    assert e.message == "name 'a' is already declared in this scope"
    assert e.line == 2
    e = err("fn f() {}\nlet f = 1;", TallyNameError)
    assert e.message == "name 'f' is already declared in this scope"
    e = err("let g = 1;\n\nfn g() {}", TallyNameError)
    assert (e.message, e.line) == ("name 'g' is already declared in this scope", 3)
    e = err("fn h(a) { let a = 1; }\nh(0);", TallyNameError)
    assert (e.message, e.line) == ("name 'a' is already declared in this scope", 1)


def test_redeclare_in_new_iteration_scope_is_fine():
    assert run("let i = 0; while i < 3 { let t = i * 2; print(t); i = i + 1; }") == "0\n2\n4\n"


def test_shadow_builtin():
    assert run('let len = 5; print(len); if true { let print = 1; } print("ok");') == "5\nok\n"
    assert run("fn str(x) { return 0; } print(str(1));") == "0\n"


def test_assign_to_builtin():
    e = err("print(1);\nlen = 3;", TallyNameError)
    assert e.message == "cannot assign to builtin 'len'"
    assert e.line == 2
    assert e.output == "1\n"


def test_assign_shadowed_builtin_ok():
    assert run("let len = 1; len = 2; print(len);") == "2\n"


def test_assign_undefined():
    e = err("x = 1;", TallyNameError)
    assert e.message == "undefined variable 'x'"


def test_assignment_rhs_evaluated_first():
    e = err('fn f() { print("rhs"); return 1; }\nnope = f();', TallyNameError)
    assert e.output == "rhs\n"
    assert e.line == 2


def test_block_scope_is_gone_after_block():
    e = err("if true { let inner = 1; }\nprint(inner);", TallyNameError)
    assert (e.message, e.line) == ("undefined variable 'inner'", 2)


# ---------------------------------------------------------------- control flow

def test_elif_chain():
    src = """
    fn grade(n) {
      if n >= 90 { return "A"; }
      elif n >= 80 { return "B"; }
      elif n >= 70 { return "C"; }
      else { return "F"; }
    }
    print(grade(95), grade(85), grade(75), grade(10));
    """
    assert run(src) == "A B C F\n"


def test_if_only_first_truthy_branch():
    assert run('if 0 { print(0); } elif "" { print(1); } elif [1] { print(2); } elif 1 { print(3); }') == "2\n"


def test_break_continue():
    src = """
    let i = 0;
    let s = [];
    while true {
      i = i + 1;
      if i % 2 == 0 { continue; }
      if i > 9 { break; }
      push(s, i);
    }
    print(s, i);
    """
    assert run(src) == "[1, 3, 5, 7, 9] 11\n"


def test_nested_loops_break_inner_only():
    src = """
    let i = 0;
    while i < 3 {
      let j = 0;
      while true {
        if j == i { break; }
        print(i, j);
        j = j + 1;
      }
      i = i + 1;
    }
    """
    assert run(src) == "1 0\n2 0\n2 1\n"


def test_return_from_inside_loop():
    src = """
    fn find(xs, v) {
      let i = 0;
      while i < len(xs) {
        if xs[i] == v { return i; }
        i = i + 1;
      }
      return -1;
    }
    print(find([5, 6, 7], 7), find([5], 9));
    """
    assert run(src) == "2 -1\n"


def test_return_nil_forms():
    assert run("fn a() { return; } fn b() {} fn c() { let x = 1; } print(a(), b(), c());") == "nil nil nil\n"


# ---------------------------------------------------------------- functions and closures

def test_counter_closure():
    src = """
    fn make_counter() {
      let n = 0;
      fn inc() { n = n + 1; return n; }
      return inc;
    }
    let c1 = make_counter();
    let c2 = make_counter();
    c1(); c1();
    print(c1(), c2(), c1);
    """
    assert run(src) == "3 1 <fn inc>\n"


def test_closures_share_scope():
    src = """
    fn pair() {
      let v = 0;
      let get = fn () { return v; };
      let set = fn (x) { v = x; };
      return [get, set];
    }
    let p = pair();
    p[1](42);
    print(p[0]());
    """
    assert run(src) == "42\n"


def test_closure_captures_by_reference_late_binding():
    src = """
    let x = 1;
    fn show() { print(x); }
    x = 2;
    show();
    fn early() { return later(); }
    fn later() { return "later"; }
    print(early());
    """
    assert run(src) == "2\nlater\n"


def test_closure_per_iteration_scope():
    src = """
    let fs = [];
    let i = 0;
    while i < 3 {
      let j = i;
      push(fs, fn () { return j; });
      i = i + 1;
    }
    print(fs[0](), fs[1](), fs[2]());
    """
    assert run(src) == "0 1 2\n"


def test_function_expression_statement_and_immediate_call():
    assert run("fn (x) { print(x * 2); }(21);") == "42\n"
    assert run("let f = fn (a, b) { return a - b; }; print(f(5, 3));") == "2\n"


def test_higher_order():
    src = """
    fn map(xs, f) {
      let out = [];
      let i = 0;
      while i < len(xs) { push(out, f(xs[i])); i = i + 1; }
      return out;
    }
    fn adder(k) { return fn (x) { return x + k; }; }
    print(map(range(4), adder(10)));
    print(map(["a", "b"], str));
    """
    assert run(src) == '[10, 11, 12, 13]\n["a", "b"]\n'


def test_recursion_fib_and_mutual():
    src = """
    fn fib(n) { if n < 2 { return n; } return fib(n - 1) + fib(n - 2); }
    fn is_even(n) { if n == 0 { return true; } return is_odd(n - 1); }
    fn is_odd(n) { if n == 0 { return false; } return is_even(n - 1); }
    print(fib(15), is_even(10), is_odd(7));
    """
    assert run(src) == "610 true true\n"


def test_recursion_depth_200_ok():
    src = """
    fn down(n) {
      if n == 1 { return 1; }
      let r = 0;
      if true { if true { while true { r = 1 + (((down(n - 1)))); break; } } }
      return r;
    }
    print(down(200));
    """
    assert run(src) == "200\n"


def test_recursion_depth_201_fails():
    src = """
    fn down(n) {
      if n == 1 { return 1; }
      return 1 + down(n - 1);
    }
    print("start");
    print(down(201));
    """
    e = err(src, TallyRecursionError)
    assert e.message == "maximum recursion depth exceeded"
    assert e.line == 4
    assert e.output == "start\n"


def test_recursion_limit_counts_active_calls_only():
    src = """
    fn down(n) { if n == 0 { return 0; } return down(n - 1); }
    let k = 0;
    while k < 5 { down(150); k = k + 1; }
    print("ok");
    """
    assert run(src) == "ok\n"


def test_recursion_limit_is_reset_after_error_in_new_run():
    with pytest.raises(TallyRecursionError):
        run("fn f() { return f(); } f();")
    assert run("fn g(n) { if n == 0 { return 0; } return g(n - 1); } print(g(199));") == "0\n"


def test_infinite_recursion_mixed_with_builtins():
    e = err("fn f(x) { return len([f(x)]); }\n\nf(1);", TallyRecursionError)
    assert e.line == 1


def test_not_callable():
    e = err("let x = 5;\nx(1);", TallyTypeError)
    assert (e.message, e.line) == ("'int' is not callable", 2)
    e = err('"s"();', TallyTypeError)
    assert e.message == "'str' is not callable"
    e = err("nil();", TallyTypeError)
    assert e.message == "'nil' is not callable"


def test_callee_and_args_evaluated_before_callable_check():
    e = err('fn t(v) { print(v); return v; }\nt(3)(t("arg"));', TallyTypeError)
    assert e.output == "3\narg\n"
    assert e.message == "'int' is not callable"


def test_arity_errors():
    e = err("fn f(a, b) {}\nf(1);", TallyTypeError)
    assert (e.message, e.line) == ("<fn f> expected 2 arguments, got 1", 2)
    e = err("let g = fn (a) {};\ng();", TallyTypeError)
    assert e.message == "<fn> expected 1 arguments, got 0"
    e = err("fn h() {} let k = h; k(1, 2, 3);", TallyTypeError)
    assert e.message == "<fn h> expected 0 arguments, got 3"


def test_builtin_errors():
    cases = [
        ("len(1, 2);", "<builtin len> expected 1 arguments, got 2"),
        ("len();", "<builtin len> expected 1 arguments, got 0"),
        ("len(5);", "len() argument must be str or list, not 'int'"),
        ("len(nil);", "len() argument must be str or list, not 'nil'"),
        ("str();", "<builtin str> expected 1 arguments, got 0"),
        ("type(1, 2);", "<builtin type> expected 1 arguments, got 2"),
        ("push([1]);", "<builtin push> expected 2 arguments, got 1"),
        ('push("s", 1);', "push() argument 1 must be list, not 'str'"),
        ("range();", "<builtin range> expected 1 or 2 arguments, got 0"),
        ("range(1, 2, 3);", "<builtin range> expected 1 or 2 arguments, got 3"),
        ("range(1.5);", "range() arguments must be int, not 'rat'"),
        ('range(1, "9");', "range() arguments must be int, not 'str'"),
        ("range(true);", "range() arguments must be int, not 'bool'"),
        ('range("a", "b", "c");', "<builtin range> expected 1 or 2 arguments, got 3"),
    ]
    for src, msg in cases:
        e = err(src, TallyTypeError)
        assert e.message == msg, src
        assert e.line == 1


def test_push_returns_nil():
    assert run("let a = []; print(push(a, 1), a);") == "nil [1]\n"


def test_call_error_line_is_paren_line():
    e = err("len\n(\n5\n);", TallyTypeError)
    assert e.line == 2


def test_error_inside_function_keeps_its_line():
    src = "fn f(x) {\n  return x + nil;\n}\n\n\nf(1);"
    e = err(src, TallyTypeError)
    assert e.line == 2


def test_name_error_line_inside_function():
    e = err("fn f() {\n\n  return missing;\n}\nprint(f());", TallyNameError)
    assert (e.message, e.line) == ("undefined variable 'missing'", 3)


# ---------------------------------------------------------------- output preservation

def test_output_preserved_on_runtime_error():
    src = 'print("one");\nprint("two", 2);\nprint([1][5]);\nprint("never");'
    e = err(src, TallyIndexError)
    assert e.output == "one\ntwo 2\n"
    assert e.line == 3


def test_print_with_failing_arg_prints_nothing():
    e = err('print("a");\nprint("b", 1 / 0, "c");', TallyZeroDivisionError)
    assert e.output == "a\n"


def test_output_includes_prints_inside_functions():
    src = "fn f(n) { print(n); if n == 0 { return 1 // n; } return f(n - 1); }\nf(2);"
    e = err(src, TallyZeroDivisionError)
    assert e.output == "2\n1\n0\n"
    assert e.line == 1


def test_syntax_error_executes_nothing():
    e = err('print("hi");\nprint(1 +);', TallySyntaxError)
    assert (e.message, e.line, e.column) == ("unexpected token ')'", 2, 10)
    assert e.output == ""


def test_error_str_format():
    e = err("print(1);\nprint(zz);", TallyNameError)
    assert str(e) == "undefined variable 'zz' (line 2)"
    e = err("let x = @;", TallySyntaxError)
    assert str(e) == "unexpected character '@' (line 1, column 9)"


# ---------------------------------------------------------------- syntax errors

@pytest.mark.parametrize("src,msg,line,col", [
    ("let x = 1 $ 2;", "unexpected character '$'", 1, 11),
    ("print(1 ! 2);", "unexpected character '!'", 1, 9),
    ("print(1.);", "unexpected character '.'", 1, 8),
    ("print(.5);", "unexpected character '.'", 1, 7),
    ("let x = 1", "unexpected end of input", 1, 10),
    ("let x = 1\n", "unexpected end of input", 2, 1),
    ("print(1)\nprint(2);", "unexpected token 'print'", 2, 1),
    ("let 5 = 1;", "unexpected token '5'", 1, 5),
    ("let if = 1;", "unexpected token 'if'", 1, 5),
    ('let x = "a" "b";', "unexpected token '\"b\"'", 1, 13),
    ("if x { print(1); } else if y { }", "unexpected token 'if'", 1, 25),
    ("if x print(1);", "unexpected token 'print'", 1, 6),
    ("while true { print(1); ", "unexpected end of input", 1, 24),
    ("print([,]);", "unexpected token ','", 1, 8),
    ("print([1,,]);", "unexpected token ','", 1, 10),
    ("fn f(a,) {}", "unexpected token ')'", 1, 8),
    ("fn f(a, b, a) {}", "duplicate parameter 'a'", 1, 12),
    ("1 + 2 = 3;", "invalid assignment target", 1, 7),
    ("f() = 3;", "invalid assignment target", 1, 5),
    ("a[1:2] = 3;", "invalid assignment target", 1, 8),
    ("x = y = 1;", "unexpected token '='", 1, 7),
    ("break;", "'break' outside loop", 1, 1),
    ("if true {\n  continue;\n}", "'continue' outside loop", 2, 3),
    ("while true { fn f() { break; } }", "'break' outside loop", 1, 23),
    ("  return 1;", "'return' outside function", 1, 3),
    ("let x = 1 ** ;", "unexpected token ';'", 1, 14),
    ("print(1 2);", "unexpected token '2'", 1, 9),
    ("let x = 1;; ", "unexpected token ';'", 1, 11),
    ("print(not);", "unexpected token ')'", 1, 10),
    ("let x = -;", "unexpected token ';'", 1, 10),
    ("print(a[]);", "unexpected token ']'", 1, 9),
    ("\tlet\tx = )", "unexpected token ')'", 1, 10),
    ("# only a comment\nlet = ;", "unexpected token '='", 2, 5),
])
def test_syntax_errors(src, msg, line, col):
    e = err(src, TallySyntaxError)
    assert (e.message, e.line, e.column) == (msg, line, col)


def test_first_syntax_error_wins():
    # a lexical error later in the source does not mask an earlier parse error
    e = err("let = 1;\nlet y = @;", TallySyntaxError)
    assert (e.message, e.line, e.column) == ("unexpected token '='", 1, 5)
    # a lexical error earlier wins over a parse error later
    e = err('let a = "\\z";\nlet = 1;', TallySyntaxError)
    assert (e.message, e.line, e.column) == ("invalid escape sequence '\\z'", 1, 10)
    # a lexical error in the offending position is reported as lexical
    e = err("let x = 1; # ok\nlet y = 2 ` 3;", TallySyntaxError)
    assert (e.message, e.line, e.column) == ("unexpected character '`'", 2, 11)


def test_syntax_valid_constructs():
    src = """
    fn f() {}
    while false {}
    if false {} elif false {} else {}
    let x = [];
    x = [ ];
    let y = [1,];
    let g = fn () { return; };
    (fn () { print("iife"); })();
    print(((1)));
    print(1 # comment ending the line
      + 2);
    """
    assert run(src) == "iife\n1\n3\n"


def test_keywords_prefix_identifiers_ok():
    assert run("let iffy = 1; let nil_ = 2; let _fn = 3; let notx = 4; print(iffy + nil_ + _fn + notx);") == "10\n"


def test_parenthesized_assignment_targets():
    assert run("let a = [1, 2]; let b = 0; (b) = 5; (a[0]) = 9; print(a, b);") == "[9, 2] 5\n"


def test_column_counts_characters_and_tabs():
    e = err("\t\u00e9 = 1;", TallySyntaxError)
    assert (e.message, e.line, e.column) == ("unexpected character '\u00e9'", 1, 2)
    e = err('print("\u00e9\u00e9", @);', TallySyntaxError)
    assert (e.message, e.line, e.column) == ("unexpected character '@'", 1, 13)


def test_unicode_inside_string_is_fine():
    assert run('print("\u00e9\u4e2d", len("\u4e2d"));') == "\u00e9\u4e2d 1\n"


def test_crlf_whitespace():
    assert run("let x = 1;\r\nprint(x);\r\n") == "1\n"


# ---------------------------------------------------------------- larger programs

def test_program_sieve_and_strings():
    src = """
    fn primes(n) {
      let is = [true] * (n + 1);
      is[0] = false; is[1] = false;
      let out = [];
      let i = 2;
      while i <= n {
        if is[i] {
          push(out, i);
          let j = i * i;
          while j <= n { is[j] = false; j = j + i; }
        }
        i = i + 1;
      }
      return out;
    }
    let ps = primes(30);
    print(ps, len(ps));
    fn join(xs, sep) {
      let s = "";
      let i = 0;
      while i < len(xs) {
        if i > 0 { s = s + sep; }
        s = s + str(xs[i]);
        i = i + 1;
      }
      return s;
    }
    print(join(ps[-3:], "-"));
    fn rev(s) { if len(s) <= 1 { return s; } return rev(s[1:]) + s[0]; }
    print(rev("stressed"));
    """
    assert run(src) == "[2, 3, 5, 7, 11, 13, 17, 19, 23, 29] 10\n19-23-29\ndesserts\n"


def test_program_exact_harmonic():
    src = """
    let h = 0;
    let k = 1;
    while k <= 10 { h = h + 1 / k; k = k + 1; }
    print(h, h // 1, type(h));
    let t = 0;
    k = 0;
    while k < 10 { t = t + 0.1; k = k + 1; }
    print(t, t == 1);
    """
    assert run(src) == "7381/2520 2 rat\n1 true\n"


# ---------------------------------------------------------------- command line

def _cli(tmp_path, src):
    f = tmp_path / "prog.ty"
    f.write_text(src, encoding="utf-8")
    env = dict(os.environ, PYTHONUTF8="1")
    env["PYTHONPATH"] = os.getcwd() + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run([sys.executable, "-m", "tally", str(f)], capture_output=True,
                          text=True, encoding="utf-8", env=env, cwd=os.getcwd(), timeout=60)


def test_cli_ok(tmp_path):
    r = _cli(tmp_path, 'print("h\u00e9", 1/4);\n')
    assert r.returncode == 0
    assert r.stdout == "h\u00e9 0.25\n"


def test_cli_runtime_error(tmp_path):
    r = _cli(tmp_path, 'print("before");\nprint(nope);\n')
    assert r.returncode == 1
    assert r.stdout == "before\n"
    assert r.stderr.strip().splitlines()[-1] == "TallyNameError: undefined variable 'nope' (line 2)"


def test_cli_syntax_error(tmp_path):
    r = _cli(tmp_path, 'print("x");\nlet = 1;\n')
    assert r.returncode == 1
    assert r.stdout == ""
    assert r.stderr.strip().splitlines()[-1] == "TallySyntaxError: unexpected token '=' (line 2, column 5)"
