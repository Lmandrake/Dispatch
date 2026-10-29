import pytest

from tally import TallyNameError, TallySyntaxError, run


def test_print_int():
    assert run("print(1 + 2);") == "3\n"


def test_print_several():
    assert run('print("a", 1, true, nil);') == "a 1 true nil\n"


def test_let_and_assign():
    assert run("let x = 1; x = x + 41; print(x);") == "42\n"


def test_if_else():
    assert run("if 1 > 2 { print(1); } else { print(2); }") == "2\n"


def test_while():
    assert run("let i = 0; while i < 3 { print(i); i = i + 1; }") == "0\n1\n2\n"


def test_function():
    assert run("fn sq(x) { return x * x; } print(sq(7));") == "49\n"


def test_list_display():
    assert run('print([1, "two", [3]]);') == '[1, "two", [3]]\n'


def test_undefined_variable():
    with pytest.raises(TallyNameError) as ei:
        run("print(1);\nprint(y);")
    assert ei.value.message == "undefined variable 'y'"
    assert ei.value.line == 2
    assert ei.value.output == "1\n"


def test_syntax_error_position():
    with pytest.raises(TallySyntaxError) as ei:
        run("let x = 1;\nlet = 2;")
    assert (ei.value.message, ei.value.line, ei.value.column) == ("unexpected token '='", 2, 5)
