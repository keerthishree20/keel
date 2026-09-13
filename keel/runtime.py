"""The semantics both engines share.

Truthiness, equality, arithmetic rules, printing and the built-in functions live
here exactly once. The benchmark compares a tree-walker against a bytecode VM,
and that comparison is only worth anything if the two run the same language, so
neither engine gets to decide these rules for itself. The conformance tests run
every program through both and require identical output.
"""

from __future__ import annotations

import time
from typing import Callable

#: Calls nest at most this deep in either engine before a clean "stack overflow"
#: error, rather than one engine erroring and the other crashing the host.
MAX_DEPTH = 512


class KeelRuntimeError(Exception):
    def __init__(self, message: str, line: int | None = None):
        super().__init__(f"line {line}: {message}" if line is not None else message)
        self.message = message
        self.line = line


class KList:
    """A Keel list. Heap-managed in the VM, plain in the tree-walker."""

    __slots__ = ("items", "marked", "freed", "__weakref__")

    def __init__(self, items: list):
        self.items = items
        self.marked = False
        #: Set by the VM's collector on sweep. Touching a freed object is a
        #: collector bug, and the VM raises rather than carrying on silently.
        self.freed = False


class Builtin:
    __slots__ = ("name", "arity", "fn")

    def __init__(self, name: str, arity: int, fn: Callable):
        self.name = name
        self.arity = arity
        self.fn = fn


# ------------------------------------------------------------------- the rules

def is_number(value) -> bool:
    # bool is a subclass of int in Python. In Keel it is not a number.
    return type(value) is int or type(value) is float


def truthy(value) -> bool:
    return not (value is None or value is False)


def equal(a, b) -> bool:
    if is_number(a) and is_number(b):
        return a == b
    if type(a) is not type(b):
        return False
    if isinstance(a, KList):
        return a is b
    return a == b


def type_name(value) -> str:
    if value is None:
        return "nil"
    if type(value) is bool:
        return "bool"
    if is_number(value):
        return "number"
    if type(value) is str:
        return "string"
    if isinstance(value, KList):
        return "list"
    return "function"


def stringify(value, _seen: set | None = None) -> str:
    if value is None:
        return "nil"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if type(value) is float:
        return repr(value)
    if type(value) is int or type(value) is str:
        return str(value)
    if isinstance(value, KList):
        seen = _seen or set()
        if id(value) in seen:
            return "[...]"
        seen.add(id(value))
        inner = ", ".join(
            f'"{item}"' if type(item) is str else stringify(item, seen) for item in value.items)
        seen.discard(id(value))
        return f"[{inner}]"
    name = getattr(value, "name", None) or getattr(getattr(value, "function", None), "name", "?")
    return f"<fn {name}>"


def arithmetic(op: str, a, b, line: int | None):
    """Every binary operator except the comparisons and equality."""
    if op == "+":
        if is_number(a) and is_number(b):
            return a + b
        if type(a) is str and type(b) is str:
            return a + b
        raise KeelRuntimeError(
            f"cannot add {type_name(a)} and {type_name(b)}", line)
    if not (is_number(a) and is_number(b)):
        raise KeelRuntimeError(
            f"operator {op} needs two numbers, got {type_name(a)} and {type_name(b)}", line)
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        if b == 0:
            raise KeelRuntimeError("division by zero", line)
        result = a / b
        return int(result) if type(a) is int and type(b) is int and a % b == 0 else result
    if op == "%":
        if b == 0:
            raise KeelRuntimeError("modulo by zero", line)
        return a % b
    raise KeelRuntimeError(f"unknown operator {op}", line)


def compare(op: str, a, b, line: int | None) -> bool:
    if not ((is_number(a) and is_number(b)) or (type(a) is str and type(b) is str)):
        raise KeelRuntimeError(
            f"cannot compare {type_name(a)} with {type_name(b)}", line)
    if op == "<":
        return a < b
    if op == "<=":
        return a <= b
    if op == ">":
        return a > b
    return a >= b


def negate(value, line: int | None):
    if not is_number(value):
        raise KeelRuntimeError(f"cannot negate {type_name(value)}", line)
    return -value


def index_get(target, index, line: int | None):
    if not isinstance(target, KList):
        raise KeelRuntimeError(f"cannot index into {type_name(target)}", line)
    if type(index) is not int:
        raise KeelRuntimeError(f"list index must be an integer, got {type_name(index)}", line)
    if not -len(target.items) <= index < len(target.items):
        raise KeelRuntimeError(
            f"index {index} out of range for a list of {len(target.items)}", line)
    return target.items[index]


def index_set(target, index, value, line: int | None):
    index_get(target, index, line)   # same checks
    target.items[index] = value
    return value


# ------------------------------------------------------------------- builtins

def make_builtins(out: Callable[[str], None]) -> dict[str, Builtin]:
    def _print(value):
        out(stringify(value))
        return None

    def _len(value):
        if type(value) is str:
            return len(value)
        if isinstance(value, KList):
            return len(value.items)
        raise KeelRuntimeError(f"len() needs a list or string, got {type_name(value)}")

    def _push(target, value):
        if not isinstance(target, KList):
            raise KeelRuntimeError(f"push() needs a list, got {type_name(target)}")
        target.items.append(value)
        return None

    def _pop(target):
        if not isinstance(target, KList):
            raise KeelRuntimeError(f"pop() needs a list, got {type_name(target)}")
        if not target.items:
            raise KeelRuntimeError("pop() from an empty list")
        return target.items.pop()

    def _str(value):
        return stringify(value)

    def _clock():
        return time.perf_counter()

    return {
        "print": Builtin("print", 1, _print),
        "len": Builtin("len", 1, _len),
        "push": Builtin("push", 2, _push),
        "pop": Builtin("pop", 1, _pop),
        "str": Builtin("str", 1, _str),
        "clock": Builtin("clock", 0, _clock),
    }
