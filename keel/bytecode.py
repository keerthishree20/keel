"""Opcodes, chunks, function prototypes, and the disassembler."""

from __future__ import annotations

from dataclasses import dataclass, field

# Each instruction is one integer in a flat list, followed by its operands, one
# integer each. The numbering is arbitrary; OPERANDS says how many to skip.
OPCODES = [
    "CONST", "NIL", "TRUE", "FALSE", "POP",
    "GET_LOCAL", "SET_LOCAL", "GET_UPVALUE", "SET_UPVALUE",
    "GET_GLOBAL", "SET_GLOBAL", "DEFINE_GLOBAL",
    "ADD", "SUB", "MUL", "DIV", "MOD", "NEG", "NOT",
    "EQ", "NEQ", "LT", "LE", "GT", "GE",
    "JUMP", "JUMP_IF_FALSE", "JUMP_IF_TRUE", "POP_JUMP_IF_FALSE", "LOOP",
    "CALL", "CLOSURE", "CLOSE_UPVALUE", "RETURN",
    "BUILD_LIST", "INDEX_GET", "INDEX_SET",
]
globals().update({name: number for number, name in enumerate(OPCODES)})

OPERANDS = {
    "CONST": 1, "GET_LOCAL": 1, "SET_LOCAL": 1, "GET_UPVALUE": 1, "SET_UPVALUE": 1,
    "GET_GLOBAL": 1, "SET_GLOBAL": 1, "DEFINE_GLOBAL": 1,
    "JUMP": 1, "JUMP_IF_FALSE": 1, "JUMP_IF_TRUE": 1, "POP_JUMP_IF_FALSE": 1, "LOOP": 1,
    "CALL": 1, "BUILD_LIST": 1,
    # CLOSURE also carries two integers per captured variable after its constant;
    # the disassembler reads the count from the prototype.
    "CLOSURE": 1,
}


@dataclass
class Chunk:
    code: list[int] = field(default_factory=list)
    constants: list = field(default_factory=list)
    lines: list[int] = field(default_factory=list)

    def emit(self, value: int, line: int) -> int:
        self.code.append(value)
        self.lines.append(line)
        return len(self.code) - 1

    def constant(self, value) -> int:
        # Reuse an identical constant rather than growing the table on every
        # mention. Compared by type as well, so 1 and 1.0 and true stay distinct.
        for position, existing in enumerate(self.constants):
            if type(existing) is type(value) and existing == value \
                    and not isinstance(value, FunctionProto):
                return position
        self.constants.append(value)
        return len(self.constants) - 1


@dataclass
class FunctionProto:
    """Compiled code for one function. Immortal: never collected, since code
    cannot become unreachable while the program that contains it is running."""

    name: str
    arity: int
    chunk: Chunk = field(default_factory=Chunk)
    upvalue_count: int = 0


def disassemble(proto: FunctionProto) -> str:
    lines: list[str] = []
    _disassemble_into(proto, lines)
    return "\n".join(lines)


def _disassemble_into(proto: FunctionProto, lines: list[str]) -> None:
    chunk = proto.chunk
    lines.append(f"== {proto.name} (arity {proto.arity}, "
                 f"{proto.upvalue_count} upvalues) ==")
    nested: list[FunctionProto] = []
    ip = 0
    previous_line = -1
    while ip < len(chunk.code):
        name = OPCODES[chunk.code[ip]]
        line = chunk.lines[ip]
        line_col = "   |" if line == previous_line else f"{line:4d}"
        previous_line = line
        operands = OPERANDS.get(name, 0)
        detail = ""
        if operands:
            operand = chunk.code[ip + 1]
            if name in ("CONST", "GET_GLOBAL", "SET_GLOBAL", "DEFINE_GLOBAL"):
                detail = f"{operand:4d}  {_show(chunk.constants[operand])}"
            elif name in ("JUMP", "JUMP_IF_FALSE", "JUMP_IF_TRUE", "POP_JUMP_IF_FALSE"):
                detail = f"{operand:4d}  -> {ip + 2 + operand}"
            elif name == "LOOP":
                detail = f"{operand:4d}  -> {ip + 2 - operand}"
            else:
                detail = f"{operand:4d}"
        lines.append(f"{ip:04d} {line_col} {name:<18} {detail}".rstrip())
        ip += 1 + operands
        if name == "CLOSURE":
            fn = chunk.constants[chunk.code[ip - 1]]
            nested.append(fn)
            for _ in range(fn.upvalue_count):
                is_local, index = chunk.code[ip], chunk.code[ip + 1]
                lines.append(f"{ip:04d}    |   {'local' if is_local else 'upvalue':<14} {index:4d}")
                ip += 2
    for fn in nested:
        lines.append("")
        _disassemble_into(fn, lines)


def _show(value) -> str:
    if isinstance(value, FunctionProto):
        return f"<fn {value.name}>"
    if isinstance(value, str):
        return repr(value)
    return str(value)
