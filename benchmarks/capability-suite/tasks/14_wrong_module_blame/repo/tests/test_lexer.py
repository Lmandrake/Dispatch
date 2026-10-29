import pytest

from ledgerkit.errors import LexError
from ledgerkit.lexer import logical_lines, split_directive, split_entry, tokenize


def test_split_simple():
    assert split_entry("2026-01-01 | Expenses:Food | Lunch | 12.50") == [
        "2026-01-01", "Expenses:Food", "Lunch", "12.50"]


def test_escaped_bar_and_backslash():
    assert split_entry(r"a | b\|c | d\\e") == ["a", "b|c", "d\\e"]


def test_quoted_field_keeps_bars_and_spaces():
    assert split_entry('x | " a | b " | y') == ["x", " a | b ", "y"]


def test_empty_trailing_fields():
    assert split_entry("a | b | |") == ["a", "b", "", ""]


@pytest.mark.parametrize("bad", ['a | b"c | d', 'a | "open', "a | b\\"])
def test_lex_errors(bad):
    with pytest.raises(LexError):
        split_entry(bad)


def test_text_after_closing_quote():
    with pytest.raises(LexError):
        split_entry('a | "b" c | d')


def test_continuation_lines():
    text = "first \\\nsecond\nthird\n"
    assert list(logical_lines(text)) == [(1, "first second"), (3, "third")]


def test_escaped_backslash_is_not_continuation():
    text = "a\\\\\nb\n"
    assert list(logical_lines(text)) == [(1, "a\\\\"), (2, "b")]


def test_unterminated_continuation():
    with pytest.raises(LexError):
        list(logical_lines("a \\"))


def test_directive_split():
    assert split_directive('alias "my card" Liabilities:Card') == [
        "alias", "my card", "Liabilities:Card"]
    assert split_directive('tag ""') == ["tag", ""]


def test_tokenize_kinds_and_numbers():
    text = "; comment\n\n!locale de_DE\n2026-01-01 | A | b | 1\n   ; indented comment\n"
    lines = list(tokenize(text))
    assert [(l.number, l.kind) for l in lines] == [(3, "directive"), (4, "entry")]
    assert lines[0].fields == ("locale", "de_DE")
