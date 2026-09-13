"""Keel: a small language with a tree-walking interpreter and a bytecode VM.

    from keel import run
    run('print("hello");')                  # the bytecode VM
    run('print("hello");', engine="tree")   # the tree-walker
"""

from .lexer import KeelSyntaxError
from .runtime import KeelRuntimeError


def run(source: str, *, engine: str = "vm", stress_gc: bool = False) -> list[str]:
    """Run a program and return what it printed, one entry per print call."""
    if engine == "tree":
        from .treewalk import run_source
        return run_source(source)
    if engine == "vm":
        from .vm import run_source
        return run_source(source, stress_gc=stress_gc)
    raise ValueError(f"engine must be 'vm' or 'tree', not {engine!r}")


__version__ = "1.0.0"
__all__ = ["run", "KeelSyntaxError", "KeelRuntimeError"]
