"""Tokens to a syntax tree.

Recursive descent for statements, one method per precedence level for
expressions. Precedence, lowest first:

    assignment   =
    or           or
    and          and
    equality     == !=
    comparison   < <= > >=
    term         + -
    factor       * / %
    unary        ! -
    call         f(x)  xs[i]
    primary      literals, names, (grouping), [lists], fn(...) {...}
"""

from __future__ import annotations

from . import ast
from .lexer import KeelSyntaxError, Token, tokenize


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0
        #: How many function bodies deep the parser is. `return` outside any
        #: function is rejected here, once, rather than each engine deciding
        #: what an unguarded top-level return means.
        self.function_depth = 0

    # ------------------------------------------------------------------ helpers

    def peek(self) -> Token:
        return self.tokens[self.pos]

    def check(self, kind: str) -> bool:
        return self.peek().kind == kind

    def match(self, *kinds: str) -> Token | None:
        if self.peek().kind in kinds:
            token = self.peek()
            self.pos += 1
            return token
        return None

    def expect(self, kind: str, what: str) -> Token:
        token = self.peek()
        if token.kind != kind:
            found = "end of input" if token.kind == "eof" else repr(token.text)
            raise KeelSyntaxError(f"expected {what}, found {found}", token.line, token.column)
        self.pos += 1
        return token

    def error(self, message: str) -> KeelSyntaxError:
        token = self.peek()
        return KeelSyntaxError(message, token.line, token.column)

    # --------------------------------------------------------------- statements

    def program(self) -> ast.Program:
        body = []
        while not self.check("eof"):
            body.append(self.statement())
        return ast.Program(body)

    def statement(self) -> ast.Node:
        token = self.peek()
        if self.match("let"):
            name = self.expect("name", "a variable name").text
            value = self.expression() if self.match("=") else None
            self.expect(";", "';' after a let")
            return ast.Let(token.line, name, value)
        if self.check("fn") and self.tokens[self.pos + 1].kind == "name":
            self.pos += 1
            name = self.expect("name", "a function name").text
            return ast.FnDecl(token.line, self.function_rest(name, token.line))
        if self.match("if"):
            self.expect("(", "'(' after if")
            condition = self.expression()
            self.expect(")", "')' after the condition")
            then = self.statement()
            otherwise = self.statement() if self.match("else") else None
            return ast.If(token.line, condition, then, otherwise)
        if self.match("while"):
            self.expect("(", "'(' after while")
            condition = self.expression()
            self.expect(")", "')' after the condition")
            return ast.While(token.line, condition, self.statement())
        if self.match("for"):
            return self.for_loop(token.line)
        if self.match("return"):
            if self.function_depth == 0:
                raise KeelSyntaxError("return outside a function", token.line, token.column)
            value = None if self.check(";") else self.expression()
            self.expect(";", "';' after return")
            return ast.Return(token.line, value)
        if self.match("{"):
            return ast.Block(token.line, self.block_rest())
        expr = self.expression()
        self.expect(";", "';' after an expression")
        return ast.ExprStmt(token.line, expr)

    def block_rest(self) -> list[ast.Node]:
        body = []
        while not self.check("}"):
            if self.check("eof"):
                raise self.error("expected '}' before end of input")
            body.append(self.statement())
        self.expect("}", "'}'")
        return body

    def for_loop(self, line: int) -> ast.Node:
        """`for (init; cond; step) body` has no node of its own. It becomes a
        block holding the initialiser and a while loop, so neither engine needs
        to know `for` exists."""
        self.expect("(", "'(' after for")
        if self.match(";"):
            init = None
        elif self.check("let"):
            init = self.statement()
        else:
            init = ast.ExprStmt(line, self.expression())
            self.expect(";", "';' after the loop initialiser")
        condition = ast.Literal(line, True) if self.check(";") else self.expression()
        self.expect(";", "';' after the loop condition")
        step = None if self.check(")") else self.expression()
        self.expect(")", "')' after the for clauses")
        body = self.statement()
        if step is not None:
            body = ast.Block(line, [body, ast.ExprStmt(line, step)])
        loop = ast.While(line, condition, body)
        return ast.Block(line, [init, loop] if init is not None else [loop])

    def function_rest(self, name: str, line: int) -> ast.Function:
        self.expect("(", "'(' before parameters")
        params: list[str] = []
        if not self.check(")"):
            while True:
                param = self.expect("name", "a parameter name").text
                if param in params:
                    raise self.error(f"parameter {param!r} is declared twice")
                params.append(param)
                if not self.match(","):
                    break
        if len(params) > 255:
            raise self.error("a function can take at most 255 parameters")
        self.expect(")", "')' after parameters")
        self.expect("{", "'{' before the function body")
        self.function_depth += 1
        try:
            body = self.block_rest()
        finally:
            self.function_depth -= 1
        return ast.Function(line, name, params, body)

    # -------------------------------------------------------------- expressions

    def expression(self) -> ast.Node:
        return self.assignment()

    def assignment(self) -> ast.Node:
        target = self.logical_or()
        if self.check("="):
            token = self.peek()
            self.pos += 1
            value = self.assignment()
            if isinstance(target, ast.Name):
                return ast.Assign(token.line, target.name, value)
            if isinstance(target, ast.Index):
                return ast.IndexAssign(token.line, target.target, target.index, value)
            raise KeelSyntaxError("cannot assign to this", token.line, token.column)
        return target

    def logical_or(self) -> ast.Node:
        left = self.logical_and()
        while token := self.match("or"):
            left = ast.Logical(token.line, "or", left, self.logical_and())
        return left

    def logical_and(self) -> ast.Node:
        left = self.equality()
        while token := self.match("and"):
            left = ast.Logical(token.line, "and", left, self.equality())
        return left

    def equality(self) -> ast.Node:
        left = self.comparison()
        while token := self.match("==", "!="):
            left = ast.Binary(token.line, token.kind, left, self.comparison())
        return left

    def comparison(self) -> ast.Node:
        left = self.term()
        while token := self.match("<", "<=", ">", ">="):
            left = ast.Binary(token.line, token.kind, left, self.term())
        return left

    def term(self) -> ast.Node:
        left = self.factor()
        while token := self.match("+", "-"):
            left = ast.Binary(token.line, token.kind, left, self.factor())
        return left

    def factor(self) -> ast.Node:
        left = self.unary()
        while token := self.match("*", "/", "%"):
            left = ast.Binary(token.line, token.kind, left, self.unary())
        return left

    def unary(self) -> ast.Node:
        if token := self.match("!", "-"):
            return ast.Unary(token.line, token.kind, self.unary())
        return self.call()

    def call(self) -> ast.Node:
        expr = self.primary()
        while True:
            if token := self.match("("):
                args: list[ast.Node] = []
                if not self.check(")"):
                    while True:
                        args.append(self.expression())
                        if not self.match(","):
                            break
                if len(args) > 255:
                    raise self.error("a call can pass at most 255 arguments")
                self.expect(")", "')' after arguments")
                expr = ast.Call(token.line, expr, args)
            elif token := self.match("["):
                index = self.expression()
                self.expect("]", "']' after an index")
                expr = ast.Index(token.line, expr, index)
            else:
                return expr

    def primary(self) -> ast.Node:
        token = self.peek()
        if self.match("number", "string"):
            return ast.Literal(token.line, token.value)
        if self.match("true"):
            return ast.Literal(token.line, True)
        if self.match("false"):
            return ast.Literal(token.line, False)
        if self.match("nil"):
            return ast.Literal(token.line, None)
        if self.match("name"):
            return ast.Name(token.line, token.text)
        if self.match("("):
            expr = self.expression()
            self.expect(")", "')' after the expression")
            return expr
        if self.match("["):
            items: list[ast.Node] = []
            if not self.check("]"):
                while True:
                    items.append(self.expression())
                    if not self.match(","):
                        break
            self.expect("]", "']' after list items")
            return ast.ListLiteral(token.line, items)
        if self.match("fn"):
            return self.function_rest("<anonymous>", token.line)
        found = "end of input" if token.kind == "eof" else repr(token.text)
        raise KeelSyntaxError(f"expected an expression, found {found}", token.line, token.column)


def parse(source: str) -> ast.Program:
    return Parser(tokenize(source)).program()
