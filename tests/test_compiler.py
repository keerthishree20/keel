"""What the compiler emits. The speed of the VM comes from these decisions."""

from __future__ import annotations

from keel import bytecode as op
from keel.bytecode import OPCODES, disassemble
from keel.compiler import compile_source


def instructions(proto) -> list[str]:
    """Opcode names only, in order, skipping operands."""
    code, names, ip = proto.chunk.code, [], 0
    while ip < len(code):
        name = OPCODES[code[ip]]
        names.append(name)
        ip += 1 + op.OPERANDS.get(name, 0)
        if name == "CLOSURE":
            ip += 2 * proto.chunk.constants[code[ip - 1]].upvalue_count
    return names


def function_named(proto, name):
    for constant in proto.chunk.constants:
        if isinstance(constant, op.FunctionProto):
            if constant.name == name:
                return constant
            found = function_named(constant, name)
            if found:
                return found
    return None


def test_locals_compile_to_slots_not_name_lookups():
    """The whole point of compiling. Inside a function no variable is looked up
    by name at run time."""
    proto = compile_source("fn f(a) { let b = a + 1; return b; }")
    body = instructions(function_named(proto, "f"))
    assert "GET_LOCAL" in body
    assert "GET_GLOBAL" not in body and "SET_GLOBAL" not in body


def test_script_level_names_are_globals():
    body = instructions(compile_source("let a = 1; print(a);"))
    assert "DEFINE_GLOBAL" in body and "GET_GLOBAL" in body
    assert "GET_LOCAL" not in body


def test_a_captured_variable_becomes_an_upvalue():
    proto = compile_source("fn outer() { let n = 0; return fn() { return n; }; }")
    outer = function_named(proto, "outer")
    inner = function_named(proto, "<anonymous>")
    assert inner.upvalue_count == 1
    assert "GET_UPVALUE" in instructions(inner)
    assert "CLOSURE" in instructions(outer)


def test_two_closures_capturing_one_variable_point_at_the_same_slot():
    proto = compile_source("""
        fn pair() {
            let v = 0;
            let get = fn() { return v; };
            let set = fn(x) { v = x; };
            return [get, set];
        }
    """)
    pair = function_named(proto, "pair")
    code, captures, ip = pair.chunk.code, [], 0
    while ip < len(code):
        name = OPCODES[code[ip]]
        ip += 1 + op.OPERANDS.get(name, 0)
        if name == "CLOSURE":
            fn = pair.chunk.constants[code[ip - 1]]
            captures.append([(code[ip + 2 * i], code[ip + 2 * i + 1]) for i in range(fn.upvalue_count)])
            ip += 2 * fn.upvalue_count
    assert captures[0] == captures[1] == [(1, 1)]


def test_a_captured_block_local_is_closed_not_popped():
    body = instructions(compile_source("""
        let keep;
        { let x = 1; keep = fn() { return x; }; }
    """))
    assert "CLOSE_UPVALUE" in body


def test_an_uncaptured_block_local_is_just_popped():
    body = instructions(compile_source("{ let x = 1; print(x); }"))
    assert "CLOSE_UPVALUE" not in body
    assert body.count("POP") >= 2


def test_capture_threads_through_intermediate_functions():
    proto = compile_source("""
        fn a() { let x = 1; fn b() { fn c() { return x; } return c; } return b; }
    """)
    b = function_named(proto, "b")
    c = function_named(proto, "c")
    assert b.upvalue_count == 1, "b must carry x through to c even though b never uses it"
    assert c.upvalue_count == 1


def test_repeated_constants_are_stored_once():
    proto = compile_source('print("same"); print("same"); print("same");')
    assert proto.chunk.constants.count("same") == 1


def test_constants_of_different_types_stay_distinct():
    """1, 1.0 and true compare equal in Python. They are three constants."""
    proto = compile_source("print(1); print(1.0);")
    assert 1 in proto.chunk.constants
    kinds = sorted(type(c).__name__ for c in proto.chunk.constants if c == 1)
    assert kinds == ["float", "int"]


def test_for_compiles_to_a_loop_instruction():
    body = instructions(compile_source("for (let i = 0; i < 3; i = i + 1) {}"))
    assert "LOOP" in body and "POP_JUMP_IF_FALSE" in body


def test_and_or_short_circuit_with_jumps():
    assert "JUMP_IF_FALSE" in instructions(compile_source("print(a and b);"))
    assert "JUMP_IF_TRUE" in instructions(compile_source("print(a or b);"))


def test_disassembly_is_readable():
    text = disassemble(compile_source("fn add(a, b) { return a + b; }\nprint(add(1, 2));"))
    assert "== <script>" in text
    assert "== add (arity 2" in text
    assert "DEFINE_GLOBAL" in text and "'add'" in text
    assert "ADD" in text and "RETURN" in text


def test_every_instruction_records_a_source_line():
    proto = compile_source("let a = 1;\nlet b = 2;\nprint(a + b);")
    assert len(proto.chunk.lines) == len(proto.chunk.code)
    assert 3 in proto.chunk.lines
