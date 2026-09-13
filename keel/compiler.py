"""Syntax tree to bytecode.

The compiler's real job is to answer, once and ahead of time, the question the
tree-walker answers on every single variable access: where does this name live?

* A **local** becomes a slot number on the VM stack. No lookup at run time at
  all, just an index.
* A variable from an enclosing function becomes an **upvalue**: an index into
  the closure's list of captured variables, resolved through however many
  functions sit in between.
* Anything else is a **global**, looked up by name, which is the only kind of
  access left that costs a dictionary probe.

Upvalues follow the design in Robert Nystrom's *Crafting Interpreters*: a
captured variable lives on the stack while its function is running and is moved
into a heap cell only when the function returns. Closures that share a variable
share the cell, so an update through one is seen by the other.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import ast
from . import bytecode as op
from .bytecode import Chunk, FunctionProto
from .lexer import KeelSyntaxError


@dataclass
class Local:
    name: str
    depth: int
    captured: bool = False


@dataclass
class FunctionState:
    proto: FunctionProto
    enclosing: "FunctionState | None"
    is_script: bool
    locals: list[Local] = field(default_factory=list)
    upvalues: list[tuple[bool, int]] = field(default_factory=list)
    scope_depth: int = 0


class Compiler:
    def __init__(self):
        self.state: FunctionState | None = None

    # ---------------------------------------------------------------- entry

    def compile_program(self, program: ast.Program) -> FunctionProto:
        script = FunctionProto("<script>", 0)
        self.state = FunctionState(script, None, is_script=True)
        # Slot 0 of every frame holds the function being called. Reserving it in
        # the compiler keeps the stack layout identical for scripts and calls.
        self.state.locals.append(Local("", 0))
        for statement in program.body:
            self.statement(statement)
        self.emit(op.NIL, 0)
        self.emit(op.RETURN, 0)
        return script

    # -------------------------------------------------------------- helpers

    @property
    def chunk(self) -> Chunk:
        return self.state.proto.chunk

    def emit(self, *values: int) -> None:
        """emit(opcode, [operands...], line). The last argument is the line."""
        *codes, line = values
        for code in codes:
            self.chunk.emit(code, line)

    def emit_jump(self, instruction: int, line: int) -> int:
        self.chunk.emit(instruction, line)
        return self.chunk.emit(0xFFFF, line)   # patched once the target is known

    def patch_jump(self, operand_at: int) -> None:
        self.chunk.code[operand_at] = len(self.chunk.code) - (operand_at + 1)

    def emit_loop(self, loop_start: int, line: int) -> None:
        self.chunk.emit(op.LOOP, line)
        self.chunk.emit(len(self.chunk.code) + 1 - loop_start, line)

    def constant(self, value, line: int) -> None:
        self.chunk.emit(op.CONST, line)
        self.chunk.emit(self.chunk.constant(value), line)

    def begin_scope(self) -> None:
        self.state.scope_depth += 1

    def end_scope(self, line: int) -> None:
        state = self.state
        state.scope_depth -= 1
        while state.locals and state.locals[-1].depth > state.scope_depth:
            # A captured local has to be hoisted off the stack before its slot is
            # reused, or the closure that captured it would read whatever the
            # next statement puts there.
            self.emit(op.CLOSE_UPVALUE if state.locals[-1].captured else op.POP, line)
            state.locals.pop()

    def add_local(self, name: str, line: int) -> None:
        state = self.state
        for local in reversed(state.locals):
            if local.depth < state.scope_depth:
                break
            if local.name == name:
                raise KeelSyntaxError(f"{name!r} is already declared in this scope", line, 0)
        if len(state.locals) >= 256:
            raise KeelSyntaxError("too many local variables in one function", line, 0)
        state.locals.append(Local(name, state.scope_depth))

    # ------------------------------------------------------------ resolution

    @staticmethod
    def resolve_local(state: FunctionState, name: str) -> int:
        for slot in range(len(state.locals) - 1, -1, -1):
            if state.locals[slot].name == name:
                return slot
        return -1

    def resolve_upvalue(self, state: FunctionState, name: str) -> int:
        """Find `name` in an enclosing function, threading it through every
        function in between. Each one gets its own upvalue entry pointing at the
        next one out, so an inner closure never reaches past its parent."""
        if state.enclosing is None:
            return -1
        slot = self.resolve_local(state.enclosing, name)
        if slot != -1:
            state.enclosing.locals[slot].captured = True
            return self.add_upvalue(state, True, slot)
        outer = self.resolve_upvalue(state.enclosing, name)
        if outer != -1:
            return self.add_upvalue(state, False, outer)
        return -1

    @staticmethod
    def add_upvalue(state: FunctionState, is_local: bool, index: int) -> int:
        for position, existing in enumerate(state.upvalues):
            if existing == (is_local, index):
                return position
        state.upvalues.append((is_local, index))
        state.proto.upvalue_count = len(state.upvalues)
        return len(state.upvalues) - 1

    def is_global_scope(self) -> bool:
        return self.state.is_script and self.state.scope_depth == 0

    # ------------------------------------------------------------ statements

    def statement(self, node: ast.Node) -> None:
        kind = type(node)
        line = node.line

        if kind is ast.ExprStmt:
            self.expression(node.expr)
            self.emit(op.POP, line)
        elif kind is ast.Let:
            if node.value is None:
                self.emit(op.NIL, line)
            else:
                self.expression(node.value)
            if self.is_global_scope():
                self.emit(op.DEFINE_GLOBAL, self.chunk.constant(node.name), line)
            else:
                # Declared after the initialiser is compiled, so `let x = x;`
                # reads the outer x, the same as the tree-walker.
                self.add_local(node.name, line)
        elif kind is ast.Block:
            self.begin_scope()
            for statement in node.body:
                self.statement(statement)
            self.end_scope(line)
        elif kind is ast.If:
            self.expression(node.condition)
            to_else = self.emit_jump(op.POP_JUMP_IF_FALSE, line)
            self.statement(node.then)
            if node.otherwise is None:
                self.patch_jump(to_else)
            else:
                to_end = self.emit_jump(op.JUMP, line)
                self.patch_jump(to_else)
                self.statement(node.otherwise)
                self.patch_jump(to_end)
        elif kind is ast.While:
            loop_start = len(self.chunk.code)
            self.expression(node.condition)
            exit_jump = self.emit_jump(op.POP_JUMP_IF_FALSE, line)
            self.statement(node.body)
            self.emit_loop(loop_start, line)
            self.patch_jump(exit_jump)
        elif kind is ast.FnDecl:
            if self.is_global_scope():
                self.function(node.function)
                self.emit(op.DEFINE_GLOBAL, self.chunk.constant(node.function.name), line)
            else:
                # Declared before its body is compiled, so the function can
                # call itself by name.
                self.add_local(node.function.name, line)
                self.function(node.function)
        elif kind is ast.Return:
            if node.value is None:
                self.emit(op.NIL, line)
            else:
                self.expression(node.value)
            self.emit(op.RETURN, line)
        else:
            raise KeelSyntaxError(f"cannot compile {kind.__name__}", line, 0)

    def function(self, fn: ast.Function) -> None:
        proto = FunctionProto(fn.name, len(fn.params))
        enclosing = self.state
        self.state = FunctionState(proto, enclosing, is_script=False)
        self.state.locals.append(Local("", 0))
        self.begin_scope()
        for param in fn.params:
            self.add_local(param, fn.line)
        for statement in fn.body:
            self.statement(statement)
        self.emit(op.NIL, fn.line)
        self.emit(op.RETURN, fn.line)
        upvalues = self.state.upvalues
        self.state = enclosing

        self.chunk.emit(op.CLOSURE, fn.line)
        self.chunk.emit(self.chunk.constant(proto), fn.line)
        for is_local, index in upvalues:
            self.chunk.emit(1 if is_local else 0, fn.line)
            self.chunk.emit(index, fn.line)

    # ----------------------------------------------------------- expressions

    def expression(self, node: ast.Node) -> None:
        kind = type(node)
        line = node.line

        if kind is ast.Literal:
            value = node.value
            if value is None:
                self.emit(op.NIL, line)
            elif value is True:
                self.emit(op.TRUE, line)
            elif value is False:
                self.emit(op.FALSE, line)
            else:
                self.constant(value, line)
        elif kind is ast.Name:
            self.variable(node.name, line, assign=False)
        elif kind is ast.Assign:
            self.expression(node.value)
            self.variable(node.name, line, assign=True)
        elif kind is ast.Binary:
            self.expression(node.left)
            self.expression(node.right)
            self.emit(_BINARY[node.op], line)
        elif kind is ast.Logical:
            self.expression(node.left)
            # The left value stays on the stack as the answer if it decides the
            # result; otherwise it is popped and the right side replaces it.
            jump = self.emit_jump(op.JUMP_IF_FALSE if node.op == "and" else op.JUMP_IF_TRUE,
                                  line)
            self.emit(op.POP, line)
            self.expression(node.right)
            self.patch_jump(jump)
        elif kind is ast.Unary:
            self.expression(node.operand)
            self.emit(op.NOT if node.op == "!" else op.NEG, line)
        elif kind is ast.Call:
            self.expression(node.callee)
            for arg in node.args:
                self.expression(arg)
            self.emit(op.CALL, len(node.args), line)
        elif kind is ast.ListLiteral:
            for item in node.items:
                self.expression(item)
            self.emit(op.BUILD_LIST, len(node.items), line)
        elif kind is ast.Index:
            self.expression(node.target)
            self.expression(node.index)
            self.emit(op.INDEX_GET, line)
        elif kind is ast.IndexAssign:
            self.expression(node.target)
            self.expression(node.index)
            self.expression(node.value)
            self.emit(op.INDEX_SET, line)
        elif kind is ast.Function:
            self.function(node)
        else:
            raise KeelSyntaxError(f"cannot compile {kind.__name__}", line, 0)

    def variable(self, name: str, line: int, *, assign: bool) -> None:
        # Slot 0 is named "", which no real name can match. A block-scoped local
        # at script level is popped from `locals` when its block closes, so a
        # later mention of the same name correctly falls through to the global.
        slot = self.resolve_local(self.state, name)
        if slot != -1:
            self.emit(op.SET_LOCAL if assign else op.GET_LOCAL, slot, line)
            return
        upvalue = self.resolve_upvalue(self.state, name)
        if upvalue != -1:
            self.emit(op.SET_UPVALUE if assign else op.GET_UPVALUE, upvalue, line)
            return
        self.emit(op.SET_GLOBAL if assign else op.GET_GLOBAL, self.chunk.constant(name), line)


_BINARY = {
    "+": op.ADD, "-": op.SUB, "*": op.MUL, "/": op.DIV, "%": op.MOD,
    "==": op.EQ, "!=": op.NEQ, "<": op.LT, "<=": op.LE, ">": op.GT, ">=": op.GE,
}


def compile_source(source: str) -> FunctionProto:
    from .parser import parse
    return Compiler().compile_program(parse(source))
