import pytest

from forgelab.formats.sexpr import SExprError, Symbol, dumps, parse


def test_parse_simple_list():
    tree = parse("(kicad_pcb (version 20221018))")
    assert tree[0] == "kicad_pcb"
    assert isinstance(tree[0], Symbol)
    assert tree[1][0] == "version"
    assert tree[1][1] == 20221018


def test_parse_quoted_string_vs_symbol():
    tree = parse('(property "Reference" R1)')
    assert tree[1] == "Reference"
    assert not isinstance(tree[1], Symbol)  # quoted -> plain str
    assert isinstance(tree[2], Symbol)  # bare  -> Symbol


def test_parse_floats():
    tree = parse("(at 100.5 -50.25 90)")
    assert tree[1] == 100.5
    assert tree[2] == -50.25
    assert tree[3] == 90


def test_parse_nested():
    tree = parse("(a (b (c 1)) (d 2))")
    assert tree[1][1][0] == "c"
    assert tree[1][1][1] == 1
    assert tree[2][1] == 2


def test_quoted_string_with_spaces_and_escapes():
    tree = parse('(name "hello world" "with \\"quote\\"")')
    assert tree[1] == "hello world"
    assert tree[2] == 'with "quote"'


def test_dumps_roundtrips_through_parse():
    tree = parse('(kicad_pcb (version 20221018) (net 1 "GND") (at 1.5 2.5 90))')
    assert parse(dumps(tree)) == tree


def test_dumps_quotes_strings_and_bares_symbols():
    text = dumps([Symbol("net"), 1, "GND"])
    assert text == '(net 1 "GND")'


def test_parse_malformed_raises():
    with pytest.raises(SExprError):
        parse("(unbalanced (parens)")
    with pytest.raises(SExprError):
        parse("nothing-here")  # top level must be a list
