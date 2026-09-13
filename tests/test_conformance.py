"""One language, two engines, identical behaviour.

Every program is run three ways: the tree-walker, the bytecode VM, and the VM
with the collector running before every allocation. The third is what keeps the
garbage collector honest; see test_gc.py.
"""

from __future__ import annotations

import textwrap

import pytest

from keel import KeelRuntimeError, run

from .programs import ERRORS, PROGRAMS

ENGINES = {
    "tree": {"engine": "tree"},
    "vm": {"engine": "vm"},
    "vm+stress-gc": {"engine": "vm", "stress_gc": True},
}


@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize("name", PROGRAMS)
def test_program_output(name, engine):
    source, expected = PROGRAMS[name]
    assert run(textwrap.dedent(source), **ENGINES[engine]) == expected


@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize("name", ERRORS)
def test_runtime_errors_match(name, engine):
    source, message, line = ERRORS[name]
    with pytest.raises(KeelRuntimeError) as caught:
        run(source, **ENGINES[engine])
    assert caught.value.message == message
    assert caught.value.line == line


def test_output_before_an_error_is_the_same_in_both_engines():
    source = 'print("one");\nprint("two");\nprint(1 / 0);\nprint("never");'
    outputs = {}
    for engine in ("tree", "vm"):
        lines: list[str] = []
        with pytest.raises(KeelRuntimeError):
            if engine == "tree":
                from keel.parser import parse
                from keel.treewalk import TreeWalker
                TreeWalker(out=lines.append).run(parse(source))
            else:
                from keel.compiler import compile_source
                from keel.vm import VM
                VM(out=lines.append).interpret(compile_source(source))
        outputs[engine] = lines
    assert outputs["tree"] == outputs["vm"] == ["one", "two"]


def test_recursion_just_under_the_limit_succeeds_in_both():
    from keel.runtime import MAX_DEPTH
    source = f"fn down(n) {{ if (n == 0) return 0; return down(n - 1); }}\nprint(down({MAX_DEPTH - 1}));"
    assert run(source, engine="tree") == run(source, engine="vm") == ["0"]


def test_redeclaring_a_local_fails_in_both_engines_at_different_times():
    """The one intentional difference, stated as a test. The compiler knows every
    local before the program runs, so it rejects this at compile time. The
    tree-walker only finds out when it executes the second declaration. The
    error is the same; the moment it appears is not."""
    from keel import KeelSyntaxError
    source = "fn f() { let a = 1; let a = 2; }"
    with pytest.raises(KeelSyntaxError, match="already declared"):
        run(source, engine="vm")
    assert run(source, engine="tree") == []          # never called, never noticed
    with pytest.raises(KeelRuntimeError, match="already declared"):
        run(source + " f();", engine="tree")
