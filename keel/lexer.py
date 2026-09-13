"""Source text to tokens."""

from __future__ import annotations

from dataclasses import dataclass

KEYWORDS = {
    "let", "fn", "return", "if", "else", "while", "for",
    "true", "false", "nil", "and", "or",
}

# Longest first, so "==" is never read as "=" twice.
SYMBOLS = [
    "==", "!=", "<=", ">=",
    "(", ")", "{", "}", "[", "]", ",", ";",
    "+", "-", "*", "/", "%", "!", "=", "<", ">",
]


class KeelSyntaxError(Exception):
    def __init__(self, message: str, line: int, column: int):
        super().__init__(f"line {line}, column {column}: {message}")
        self.line = line
        self.column = column


@dataclass(frozen=True, slots=True)
class Token:
    kind: str      # "number", "string", "name", a keyword, a symbol, or "eof"
    text: str
    value: object
    line: int
    column: int


def tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    i, line, line_start = 0, 1, 0
    length = len(source)

    while i < length:
        ch = source[i]
        column = i - line_start + 1

        if ch == "\n":
            line += 1
            i += 1
            line_start = i
            continue
        if ch in " \t\r":
            i += 1
            continue
        if ch == "/" and source.startswith("//", i):
            while i < length and source[i] != "\n":
                i += 1
            continue

        if ch.isdigit():
            start = i
            while i < length and source[i].isdigit():
                i += 1
            is_float = i + 1 < length and source[i] == "." and source[i + 1].isdigit()
            if is_float:
                i += 1
                while i < length and source[i].isdigit():
                    i += 1
            text = source[start:i]
            tokens.append(Token("number", text, float(text) if is_float else int(text),
                                line, column))
            continue

        if ch.isalpha() or ch == "_":
            start = i
            while i < length and (source[i].isalnum() or source[i] == "_"):
                i += 1
            text = source[start:i]
            kind = text if text in KEYWORDS else "name"
            tokens.append(Token(kind, text, text, line, column))
            continue

        if ch == '"':
            i += 1
            chars: list[str] = []
            while True:
                if i >= length or source[i] == "\n":
                    raise KeelSyntaxError("unterminated string", line, column)
                c = source[i]
                if c == '"':
                    i += 1
                    break
                if c == "\\":
                    i += 1
                    escape = source[i] if i < length else ""
                    mapped = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(escape)
                    if mapped is None:
                        raise KeelSyntaxError(f"unknown escape \\{escape}", line, i - line_start)
                    chars.append(mapped)
                    i += 1
                    continue
                chars.append(c)
                i += 1
            text = "".join(chars)
            tokens.append(Token("string", text, text, line, column))
            continue

        for symbol in SYMBOLS:
            if source.startswith(symbol, i):
                tokens.append(Token(symbol, symbol, None, line, column))
                i += len(symbol)
                break
        else:
            raise KeelSyntaxError(f"unexpected character {ch!r}", line, column)

    tokens.append(Token("eof", "", None, line, len(source) - line_start + 1))
    return tokens
