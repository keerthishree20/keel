"""The stack virtual machine.

One loop, one flat list of integers per function, one shared value stack.

The hot loop is written for CPython rather than for elegance. The current
function's code, constants and instruction pointer live in local variables,
because a local read is several times cheaper than an attribute read, and they
are reloaded only when a call or return changes the frame. Dispatch is an
if-chain ordered by how often each instruction runs in the benchmark programs,
so the common instructions are found in two or three comparisons. The arithmetic
instructions have an inline fast path for two integers and fall back to the
shared rules in `runtime` for everything else, which keeps the semantics
identical to the tree-walker without paying for the general case every time.
"""

from __future__ import annotations

from typing import Callable

from . import bytecode as op
from .bytecode import FunctionProto
from .gc import GCError, Heap, ObjClosure, ObjUpvalue
from .runtime import (MAX_DEPTH, Builtin, KeelRuntimeError, KList, arithmetic, compare, equal,
                      index_get, index_set, make_builtins, negate, truthy, type_name)

CONST, NIL, TRUE, FALSE, POP = op.CONST, op.NIL, op.TRUE, op.FALSE, op.POP
GET_LOCAL, SET_LOCAL, GET_UPVALUE, SET_UPVALUE = op.GET_LOCAL, op.SET_LOCAL, op.GET_UPVALUE, op.SET_UPVALUE
GET_GLOBAL, SET_GLOBAL, DEFINE_GLOBAL = op.GET_GLOBAL, op.SET_GLOBAL, op.DEFINE_GLOBAL
ADD, SUB, MUL, DIV, MOD, NEG, NOT = op.ADD, op.SUB, op.MUL, op.DIV, op.MOD, op.NEG, op.NOT
EQ, NEQ, LT, LE, GT, GE = op.EQ, op.NEQ, op.LT, op.LE, op.GT, op.GE
JUMP, JUMP_IF_FALSE, JUMP_IF_TRUE, POP_JUMP_IF_FALSE, LOOP = (
    op.JUMP, op.JUMP_IF_FALSE, op.JUMP_IF_TRUE, op.POP_JUMP_IF_FALSE, op.LOOP)
CALL, CLOSURE, CLOSE_UPVALUE, RETURN = op.CALL, op.CLOSURE, op.CLOSE_UPVALUE, op.RETURN
BUILD_LIST, INDEX_GET, INDEX_SET = op.BUILD_LIST, op.INDEX_GET, op.INDEX_SET


class Frame:
    __slots__ = ("closure", "ip", "base")

    def __init__(self, closure: ObjClosure, ip: int, base: int):
        self.closure = closure
        self.ip = ip
        self.base = base


class VM:
    def __init__(self, out: Callable[[str], None] | None = None, *, stress_gc: bool = False,
                 gc_threshold: int | None = None):
        self.output: list[str] = []
        self.globals: dict[str, object] = dict(make_builtins(out or self.output.append))
        self.stack: list = []
        self.frames: list[Frame] = []
        #: Open upvalues by absolute stack slot. At most one per slot, so every
        #: closure capturing the same variable shares one cell.
        self.open_upvalues: dict[int, ObjUpvalue] = {}
        kwargs = {"stress": stress_gc}
        if gc_threshold is not None:
            kwargs["threshold"] = gc_threshold
        self.heap = Heap(**kwargs)

    # ---------------------------------------------------------------- the gc

    def mark_roots(self, mark) -> None:
        for value in self.stack:
            mark(value)
        for frame in self.frames:
            mark(frame.closure)
        for value in self.globals.values():
            mark(value)
        for upvalue in self.open_upvalues.values():
            mark(upvalue)

    def collect(self) -> int:
        return self.heap.collect(self)

    # ------------------------------------------------------------- upvalues

    def capture(self, slot: int) -> ObjUpvalue:
        upvalue = self.open_upvalues.get(slot)
        if upvalue is None:
            upvalue = ObjUpvalue(slot)
            self.heap.register(self, upvalue)
            self.open_upvalues[slot] = upvalue
        return upvalue

    def close_upvalues(self, from_slot: int) -> None:
        stack = self.stack
        for slot in [s for s in self.open_upvalues if s >= from_slot]:
            upvalue = self.open_upvalues.pop(slot)
            upvalue.value = stack[slot]
            upvalue.slot = -1

    # ------------------------------------------------------------------ run

    def interpret(self, proto: FunctionProto) -> None:
        script = ObjClosure(proto)
        self.stack.append(script)
        self.heap.register(self, script)
        self.frames.append(Frame(script, 0, 0))
        try:
            self.run()
        except KeelRuntimeError:
            self.stack.clear()
            self.frames.clear()
            self.open_upvalues.clear()
            raise

    def run(self) -> None:
        stack = self.stack
        frames = self.frames
        heap = self.heap
        globals_ = self.globals

        frame = frames[-1]
        code = frame.closure.function.chunk.code
        consts = frame.closure.function.chunk.constants
        lines = frame.closure.function.chunk.lines
        ip = frame.ip
        base = frame.base

        while True:
            instruction = code[ip]
            ip += 1

            if instruction == GET_LOCAL:
                stack.append(stack[base + code[ip]])
                ip += 1

            elif instruction == CONST:
                stack.append(consts[code[ip]])
                ip += 1

            elif instruction == ADD:
                b = stack.pop()
                a = stack[-1]
                if type(a) is int and type(b) is int:
                    stack[-1] = a + b
                else:
                    stack[-1] = arithmetic("+", a, b, lines[ip - 1])

            elif instruction == LT:
                b = stack.pop()
                a = stack[-1]
                if type(a) is int and type(b) is int:
                    stack[-1] = a < b
                else:
                    stack[-1] = compare("<", a, b, lines[ip - 1])

            elif instruction == POP_JUMP_IF_FALSE:
                value = stack.pop()
                if value is None or value is False:
                    ip += code[ip] + 1
                else:
                    ip += 1

            elif instruction == SET_LOCAL:
                stack[base + code[ip]] = stack[-1]
                ip += 1

            elif instruction == POP:
                stack.pop()

            elif instruction == LOOP:
                ip -= code[ip] - 1

            elif instruction == GET_GLOBAL:
                name = consts[code[ip]]
                ip += 1
                try:
                    stack.append(globals_[name])
                except KeyError:
                    raise KeelRuntimeError(f"undefined variable {name!r}",
                                           lines[ip - 1]) from None

            elif instruction == SUB:
                b = stack.pop()
                a = stack[-1]
                if type(a) is int and type(b) is int:
                    stack[-1] = a - b
                else:
                    stack[-1] = arithmetic("-", a, b, lines[ip - 1])

            elif instruction == CALL:
                argc = code[ip]
                ip += 1
                callee = stack[-1 - argc]
                if type(callee) is ObjClosure:
                    if callee.freed:
                        raise GCError("called a closure that was already freed",
                                      lines[ip - 1])
                    proto = callee.function
                    if argc != proto.arity:
                        raise KeelRuntimeError(
                            f"{proto.name}() takes {proto.arity} argument"
                            f"{'' if proto.arity == 1 else 's'}, got {argc}",
                            lines[ip - 1])
                    # frames includes the script's own frame, so this allows exactly
                    # MAX_DEPTH nested calls, the same limit the tree-walker enforces.
                    if len(frames) > MAX_DEPTH:
                        raise KeelRuntimeError("stack overflow", lines[ip - 1])
                    frame.ip = ip
                    frame = Frame(callee, 0, len(stack) - argc - 1)
                    frames.append(frame)
                    code = proto.chunk.code
                    consts = proto.chunk.constants
                    lines = proto.chunk.lines
                    ip = 0
                    base = frame.base
                elif type(callee) is Builtin:
                    if argc != callee.arity:
                        raise KeelRuntimeError(
                            f"{callee.name}() takes {callee.arity} argument"
                            f"{'' if callee.arity == 1 else 's'}, got {argc}",
                            lines[ip - 1])
                    args = stack[len(stack) - argc:]
                    for arg in args:
                        if type(arg) is KList and arg.freed:
                            raise GCError("passed a list that was already freed",
                                          lines[ip - 1])
                    del stack[len(stack) - argc - 1:]
                    try:
                        stack.append(callee.fn(*args))
                    except KeelRuntimeError as exc:
                        raise KeelRuntimeError(exc.message, lines[ip - 1]) from None
                else:
                    raise KeelRuntimeError(f"cannot call {type_name(callee)}",
                                           lines[ip - 1])

            elif instruction == RETURN:
                result = stack.pop()
                if self.open_upvalues:
                    self.close_upvalues(base)
                frames.pop()
                del stack[base:]
                if not frames:
                    return
                stack.append(result)
                frame = frames[-1]
                code = frame.closure.function.chunk.code
                consts = frame.closure.function.chunk.constants
                lines = frame.closure.function.chunk.lines
                ip = frame.ip
                base = frame.base

            elif instruction == GET_UPVALUE:
                upvalue = frame.closure.upvalues[code[ip]]
                ip += 1
                if upvalue.freed:
                    raise GCError("read a captured variable that was already freed",
                                  lines[ip - 1])
                stack.append(stack[upvalue.slot] if upvalue.slot >= 0 else upvalue.value)

            elif instruction == SET_UPVALUE:
                upvalue = frame.closure.upvalues[code[ip]]
                ip += 1
                if upvalue.freed:
                    raise GCError("wrote a captured variable that was already freed",
                                  lines[ip - 1])
                if upvalue.slot >= 0:
                    stack[upvalue.slot] = stack[-1]
                else:
                    upvalue.value = stack[-1]

            elif instruction == LE:
                b = stack.pop()
                a = stack[-1]
                if type(a) is int and type(b) is int:
                    stack[-1] = a <= b
                else:
                    stack[-1] = compare("<=", a, b, lines[ip - 1])

            elif instruction == GT:
                b = stack.pop()
                a = stack[-1]
                if type(a) is int and type(b) is int:
                    stack[-1] = a > b
                else:
                    stack[-1] = compare(">", a, b, lines[ip - 1])

            elif instruction == GE:
                b = stack.pop()
                a = stack[-1]
                if type(a) is int and type(b) is int:
                    stack[-1] = a >= b
                else:
                    stack[-1] = compare(">=", a, b, lines[ip - 1])

            elif instruction == EQ:
                b = stack.pop()
                stack[-1] = equal(stack[-1], b)

            elif instruction == NEQ:
                b = stack.pop()
                stack[-1] = not equal(stack[-1], b)

            elif instruction == MUL:
                b = stack.pop()
                a = stack[-1]
                if type(a) is int and type(b) is int:
                    stack[-1] = a * b
                else:
                    stack[-1] = arithmetic("*", a, b, lines[ip - 1])

            elif instruction == DIV:
                b = stack.pop()
                stack[-1] = arithmetic("/", stack[-1], b, lines[ip - 1])

            elif instruction == MOD:
                b = stack.pop()
                a = stack[-1]
                if type(a) is int and type(b) is int and b:
                    stack[-1] = a % b
                else:
                    stack[-1] = arithmetic("%", a, b, lines[ip - 1])

            elif instruction == JUMP:
                ip += code[ip] + 1

            elif instruction == JUMP_IF_FALSE:
                value = stack[-1]
                if value is None or value is False:
                    ip += code[ip] + 1
                else:
                    ip += 1

            elif instruction == JUMP_IF_TRUE:
                value = stack[-1]
                if value is None or value is False:
                    ip += 1
                else:
                    ip += code[ip] + 1

            elif instruction == NIL:
                stack.append(None)

            elif instruction == TRUE:
                stack.append(True)

            elif instruction == FALSE:
                stack.append(False)

            elif instruction == NOT:
                stack[-1] = not truthy(stack[-1])

            elif instruction == NEG:
                stack[-1] = negate(stack[-1], lines[ip - 1])

            elif instruction == INDEX_GET:
                index = stack.pop()
                target = stack[-1]
                if type(target) is KList:
                    if target.freed:
                        raise GCError("indexed a list that was already freed", lines[ip - 1])
                    items = target.items
                    if type(index) is int and -len(items) <= index < len(items):
                        stack[-1] = items[index]
                        continue
                # Anything unusual, including every error, takes the shared path
                # so the messages stay identical to the tree-walker's.
                stack[-1] = index_get(target, index, lines[ip - 1])

            elif instruction == INDEX_SET:
                value = stack.pop()
                index = stack.pop()
                target = stack[-1]
                if type(target) is KList and target.freed:
                    raise GCError("assigned into a list that was already freed",
                                  lines[ip - 1])
                stack[-1] = index_set(target, index, value, lines[ip - 1])

            elif instruction == BUILD_LIST:
                count = code[ip]
                ip += 1
                # Registered while the items are still on the stack, so a
                # collection triggered here sees them as roots. The registration
                # is inlined: at hundreds of thousands of allocations, a method
                # call each was a tenth of the whole run.
                if heap.stress or heap.allocations_since >= heap.threshold:
                    heap.collect(self)
                if count:
                    split = len(stack) - count
                    new_list = KList(stack[split:])
                    del stack[split:]
                else:
                    new_list = KList([])
                heap.objects.append(new_list)
                heap.allocations_since += 1
                stack.append(new_list)

            elif instruction == DEFINE_GLOBAL:
                globals_[consts[code[ip]]] = stack.pop()
                ip += 1

            elif instruction == SET_GLOBAL:
                name = consts[code[ip]]
                ip += 1
                if name not in globals_:
                    raise KeelRuntimeError(f"undefined variable {name!r}", lines[ip - 1])
                globals_[name] = stack[-1]

            elif instruction == CLOSURE:
                proto = consts[code[ip]]
                ip += 1
                closure = ObjClosure(proto)
                heap.register(self, closure)
                # On the stack before its upvalues are allocated: each capture
                # below may trigger a collection, and the partly built closure
                # has to be a root when that happens.
                stack.append(closure)
                for _ in range(proto.upvalue_count):
                    is_local = code[ip]
                    index = code[ip + 1]
                    ip += 2
                    if is_local:
                        closure.upvalues.append(self.capture(base + index))
                    else:
                        closure.upvalues.append(frame.closure.upvalues[index])

            elif instruction == CLOSE_UPVALUE:
                if self.open_upvalues:
                    self.close_upvalues(len(stack) - 1)
                stack.pop()

            else:
                raise KeelRuntimeError(f"unknown instruction {instruction}", lines[ip - 1])


def run_source(source: str, *, stress_gc: bool = False) -> list[str]:
    from .compiler import compile_source
    vm = VM(stress_gc=stress_gc)
    vm.interpret(compile_source(source))
    return vm.output
