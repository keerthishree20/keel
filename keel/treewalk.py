"""The tree-walking interpreter: the baseline.

Deliberately the obvious design, because the point is to measure what a
compiler and a VM buy over it. Every evaluation walks the syntax tree and
dispatches on the node's type; every variable lookup climbs a chain of
dictionaries; `return` is a Python exception unwinding back to the call. Each
of those is a known cost, and each is something the bytecode engine removes:
the compiler resolves variables to stack slots ahead of time, and a return is a
jump.

It is not a straw man. It is correct, it runs the same conformance suite as the
VM, and it is roughly how a first interpreter gets written.
"""

from __future__ import annotations

import sys
from typing import Callable

from . import ast
from .runtime import (MAX_DEPTH, Builtin, KeelRuntimeError, KList, arithmetic, compare,
                      equal, index_get, index_set, make_builtins, negate, stringify, truthy,
                      type_name)


class Environment:
    __slots__ = ("values", "parent")

    def __init__(self, parent: "Environment | None" = None):
        self.values: dict[str, object] = {}
        self.parent = parent

    def lookup(self, name: str, line: int):
        env = self
        while env is not None:
            if name in env.values:
                return env.values[name]
            env = env.parent
        raise KeelRuntimeError(f"undefined variable {name!r}", line)

    def assign(self, name: str, value, line: int):
        env = self
        while env is not None:
            if name in env.values:
                env.values[name] = value
                return value
            env = env.parent
        raise KeelRuntimeError(f"undefined variable {name!r}", line)


class TreeFunction:
    __slots__ = ("name", "params", "body", "closure")

    def __init__(self, name: str, params: list[str], body: list[ast.Node], closure: Environment):
        self.name = name
        self.params = params
        self.body = body
        self.closure = closure


class _Return(Exception):
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value


class TreeWalker:
    def __init__(self, out: Callable[[str], None] | None = None):
        self.output: list[str] = []
        emit = out or self.output.append
        self.globals = Environment()
        for name, builtin in make_builtins(emit).items():
            self.globals.values[name] = builtin
        self.depth = 0

    def run(self, program: ast.Program) -> None:
        previous = sys.getrecursionlimit()
        # Each Keel call costs a dozen or so Python frames here. Raising the
        # limit lets MAX_DEPTH, not the host, decide when recursion is too deep.
        sys.setrecursionlimit(max(previous, MAX_DEPTH * 40))
        try:
            self.execute_block(program.body, self.globals)
        finally:
            sys.setrecursionlimit(previous)

    # ------------------------------------------------------------- statements

    def execute_block(self, body: list[ast.Node], env: Environment) -> None:
        for statement in body:
            self.execute(statement, env)

    def execute(self, node: ast.Node, env: Environment) -> None:
        kind = type(node)
        if kind is ast.ExprStmt:
            self.evaluate(node.expr, env)
        elif kind is ast.Let:
            if node.name in env.values and env is not self.globals:
                raise KeelRuntimeError(
                    f"{node.name!r} is already declared in this scope", node.line)
            env.values[node.name] = None if node.value is None else self.evaluate(node.value, env)
        elif kind is ast.Block:
            self.execute_block(node.body, Environment(env))
        elif kind is ast.If:
            if truthy(self.evaluate(node.condition, env)):
                self.execute(node.then, env)
            elif node.otherwise is not None:
                self.execute(node.otherwise, env)
        elif kind is ast.While:
            while truthy(self.evaluate(node.condition, env)):
                self.execute(node.body, env)
        elif kind is ast.FnDecl:
            fn = node.function
            env.values[fn.name] = TreeFunction(fn.name, fn.params, fn.body, env)
        elif kind is ast.Return:
            raise _Return(None if node.value is None else self.evaluate(node.value, env))
        else:
            raise KeelRuntimeError(f"cannot execute {kind.__name__}", node.line)

    # ------------------------------------------------------------ expressions

    def evaluate(self, node: ast.Node, env: Environment):
        kind = type(node)
        if kind is ast.Literal:
            return node.value
        if kind is ast.Name:
            return env.lookup(node.name, node.line)
        if kind is ast.Binary:
            left = self.evaluate(node.left, env)
            right = self.evaluate(node.right, env)
            op = node.op
            if op == "==":
                return equal(left, right)
            if op == "!=":
                return not equal(left, right)
            if op in ("<", "<=", ">", ">="):
                return compare(op, left, right, node.line)
            return arithmetic(op, left, right, node.line)
        if kind is ast.Assign:
            return env.assign(node.name, self.evaluate(node.value, env), node.line)
        if kind is ast.Call:
            return self.call(node, env)
        if kind is ast.Logical:
            left = self.evaluate(node.left, env)
            if node.op == "or":
                return left if truthy(left) else self.evaluate(node.right, env)
            return self.evaluate(node.right, env) if truthy(left) else left
        if kind is ast.Unary:
            value = self.evaluate(node.operand, env)
            return (not truthy(value)) if node.op == "!" else negate(value, node.line)
        if kind is ast.Index:
            return index_get(self.evaluate(node.target, env),
                             self.evaluate(node.index, env), node.line)
        if kind is ast.IndexAssign:
            target = self.evaluate(node.target, env)
            index = self.evaluate(node.index, env)
            return index_set(target, index, self.evaluate(node.value, env), node.line)
        if kind is ast.ListLiteral:
            return KList([self.evaluate(item, env) for item in node.items])
        if kind is ast.Function:
            return TreeFunction(node.name, node.params, node.body, env)
        raise KeelRuntimeError(f"cannot evaluate {kind.__name__}", node.line)

    def call(self, node: ast.Call, env: Environment):
        callee = self.evaluate(node.callee, env)
        args = [self.evaluate(arg, env) for arg in node.args]

        if isinstance(callee, Builtin):
            if len(args) != callee.arity:
                raise KeelRuntimeError(
                    f"{callee.name}() takes {callee.arity} argument"
                    f"{'' if callee.arity == 1 else 's'}, got {len(args)}", node.line)
            try:
                return callee.fn(*args)
            except KeelRuntimeError as exc:
                raise KeelRuntimeError(exc.message, node.line) from None

        if not isinstance(callee, TreeFunction):
            raise KeelRuntimeError(f"cannot call {type_name(callee)}", node.line)
        if len(args) != len(callee.params):
            raise KeelRuntimeError(
                f"{callee.name}() takes {len(callee.params)} argument"
                f"{'' if len(callee.params) == 1 else 's'}, got {len(args)}", node.line)
        if self.depth >= MAX_DEPTH:
            raise KeelRuntimeError("stack overflow", node.line)

        frame = Environment(callee.closure)
        for param, arg in zip(callee.params, args):
            frame.values[param] = arg
        self.depth += 1
        try:
            self.execute_block(callee.body, frame)
        except _Return as ret:
            return ret.value
        finally:
            self.depth -= 1
        return None


def run_source(source: str) -> list[str]:
    from .parser import parse
    walker = TreeWalker()
    walker.run(parse(source))
    return walker.output
