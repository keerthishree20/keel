"""Lexing and parsing."""

from __future__ import annotations

import re

import pytest

from keel import KeelSyntaxError, ast
from keel.lexer import tokenize
from keel.parser import parse


def kinds(source: str) -> list[str]:
    return [t.kind for t in tokenize(source)]


def test_tokens_and_keywords():
    assert kinds("let x = 1;") == ["let", "name", "=", "number", ";", "eof"]
    assert kinds("fn if else while for return true false nil and or") == [
        "fn", "if", "else", "while", "for", "return", "true", "false", "nil", "and", "or", "eof"]


def test_two_character_operators_are_not_split():
    assert kinds("== != <= >=") == ["==", "!=", "<=", ">=", "eof"]


def test_numbers_keep_their_type():
    tokens = tokenize("7 7.5")
    assert tokens[0].value == 7 and type(tokens[0].value) is int
    assert tokens[1].value == 7.5 and type(tokens[1].value) is float


def test_a_trailing_dot_is_not_a_float():
    """A float needs a digit after the point. Keel has no `.` operator, so a
    bare trailing dot is an error rather than silently becoming 7.0."""
    with pytest.raises(KeelSyntaxError, match="unexpected character '.'"):
        tokenize("7.")


def test_string_escapes():
    assert tokenize(r'"a\nb\t\"c\\"')[0].value == 'a\nb\t"c\\'


def test_comments_are_skipped():
    assert kinds("1 // everything here is ignored\n2") == ["number", "number", "eof"]


def test_lines_and_columns_are_tracked():
    token = tokenize("let a;\n  let b;")[3]
    assert (token.kind, token.line, token.column) == ("let", 2, 3)


@pytest.mark.parametrize("source,message", [
    ('"unterminated', "unterminated string"),
    ('"bad \\q escape"', "unknown escape"),
    ("let x = @;", "unexpected character"),
])
def test_lexer_errors(source, message):
    with pytest.raises(KeelSyntaxError, match=message):
        tokenize(source)


def test_precedence_builds_the_right_tree():
    expr = parse("1 + 2 * 3;").body[0].expr
    assert isinstance(expr, ast.Binary) and expr.op == "+"
    assert isinstance(expr.right, ast.Binary) and expr.right.op == "*"


def test_assignment_is_right_associative():
    expr = parse("a = b = 1;").body[0].expr
    assert isinstance(expr, ast.Assign) and isinstance(expr.value, ast.Assign)


def test_and_binds_tighter_than_or():
    expr = parse("a or b and c;").body[0].expr
    assert expr.op == "or" and expr.right.op == "and"


def test_calls_and_indexing_chain():
    expr = parse("f(1)[2](3);").body[0].expr
    assert isinstance(expr, ast.Call)
    assert isinstance(expr.callee, ast.Index)
    assert isinstance(expr.callee.target, ast.Call)


def test_for_becomes_a_block_around_a_while():
    """No engine has to know `for` exists."""
    node = parse("for (let i = 0; i < 3; i = i + 1) print(i);").body[0]
    assert isinstance(node, ast.Block)
    assert isinstance(node.body[0], ast.Let)
    assert isinstance(node.body[1], ast.While)


@pytest.mark.parametrize("source,message", [
    ("let = 3;", "expected a variable name"),
    ("print(1", "expected ')' after arguments"),
    ("1 + ;", "expected an expression"),
    ("{ let a = 1;", "expected '}' before end of input"),
    ("3 = 4;", "cannot assign to this"),
    ("return 1;", "return outside a function"),
    ("fn f(a, a) {}", "declared twice"),
    ("let x = 1", "expected ';' after a let"),
])
def test_parse_errors(source, message):
    with pytest.raises(KeelSyntaxError, match=re.escape(message)):
        parse(source)


def test_a_syntax_error_reports_where():
    with pytest.raises(KeelSyntaxError) as caught:
        parse("let a = 1;\nlet b = ;")
    assert caught.value.line == 2
