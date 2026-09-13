# Keel

A small language with two complete implementations: a tree-walking interpreter
and a bytecode compiler with a stack virtual machine and a mark-and-sweep garbage
collector. Pure Python, no dependencies.

```
fn make_accumulator(start) {
    let total = start;
    return fn(amount) { total = total + amount; return total; };
}
let wallet = make_accumulator(100);
wallet(25);
print(wallet(-40));      // 85
```

```bash
keel run program.keel            # bytecode VM
keel run program.keel --tree     # tree-walker
keel dis program.keel            # show the bytecode
```

---

## The result

Median of five runs per program. Parsing excluded from both engines; compile
time charged to the VM. Intel Core i5-11320H, Python 3.12.13. Reproduce with
`make bench`.

| Program | What it stresses | Tree-walker | VM | Speedup |
|---|---|---:|---:|---:|
| `fib` | function calls | 1,336 ms | 447 ms | **2.99x** |
| `loop_locals` | loop over local variables | 2,423 ms | 1,150 ms | **2.11x** |
| `nested` | nested loops with a call inside | 1,167 ms | 581 ms | **2.01x** |
| `closures` | captured variables | 1,304 ms | 731 ms | **1.78x** |
| `loop_globals` | the same loop over globals | 2,430 ms | 1,425 ms | **1.71x** |
| `lists` | building and indexing | 1,205 ms | 757 ms | **1.59x** |
| `garbage` | allocation pressure | 1,208 ms | 1,031 ms | **1.17x** |

Compilation takes under 0.2 ms for every program here, so it never decides the
outcome.

**The VM wins everything, by between 1.2 and 3 times.** It is a smaller margin
than the same design gets in C, and the reasons are below.

### Where the speedup comes from

**Calls, most of all.** `fib` is almost nothing but calls, and it shows the
largest gap. Each tree-walker call allocates a fresh dictionary for its
variables and uses a Python exception to carry `return` back up the stack. A VM
call pushes a frame and a return is a jump.

**Knowing where variables live.** The two loop programs are the same loop, once
over local variables and once over globals. In the global version both engines
look every name up in a dictionary, so the only difference left is not walking
the tree. The gap between them, 2.11 against 1.71, is what resolving names to
stack slots at compile time is worth on its own: about 23% more.

**Allocation is where the VM gains least.** `garbage` makes a quarter of a
million short-lived lists. The collector's pauses total 54 ms of the run, so
collection itself is cheap. What costs is owning the objects at all: every list
is registered with the heap when it is made and examined when it is swept, and
the tree-walker, which lets Python manage its memory, pays neither.

### The fast paths, measured separately

After the first measurement a profile of `garbage` showed two avoidable costs: a
method call to register every allocation, and the general-purpose routines for
`*`, `%` and list indexing, which `+` and `<` already bypassed. Those got inline
paths for the common case, with anything unusual, including every error, still
routed through the shared rules so error messages stay identical.

The tree-walker did not get equivalent tuning, so the difference is shown rather
than folded in:

| Program | Before | After |
|---|---:|---:|
| `garbage` | 1.04x | 1.17x |
| `loop_locals` | 1.93x | 2.11x |
| `nested` | 1.82x | 2.01x |
| `loop_globals` | 1.56x | 1.71x |
| `lists` | 1.54x | 1.59x |
| `fib` | 2.95x | 2.99x |
| `closures` | 1.85x | 1.78x |

So most of the speedup is the architecture, and roughly a tenth of it on
the arithmetic-heavy programs is the tuning. `closures` moved the other way,
within run-to-run noise.

---

## Two engines, one language

A speed comparison between two interpreters means nothing if they disagree about
what programs mean. So neither engine decides the rules: truthiness, equality,
arithmetic, printing and every built-in function live in one shared module, and
both engines call it.

Then it is checked. Every conformance program runs three ways, on the
tree-walker, on the VM, and on the VM with the collector running before every
single allocation, and all three must print exactly the same thing. Sixteen
programs that must fail do so with the same message on the same line in both
engines.

There is one intentional difference, and it has a test of its own. Declaring
the same local twice in one scope is an error in both, but the compiler knows
every local before the program runs and rejects it at compile time, while the
tree-walker only notices when it reaches the second declaration.

---

## The language

Numbers, strings, booleans, `nil`, lists and first-class functions with
closures. `let`, `if`/`else`, `while`, `for`, `fn`, `return`, `and`, `or`.
Built-ins: `print`, `len`, `push`, `pop`, `str`, `clock`.

Only `nil` and `false` are falsy. `true == 1` is false, even though the host
language disagrees. Integer division that comes out whole stays an integer, so
`8 / 4` is `2` and `7 / 2` is `3.5`.

`for` has no implementation of its own. The parser rewrites it into a block
holding the initialiser and a `while` loop, so neither engine needs to know it
exists.

---

## How the VM works

### Compiling

The compiler's real job is answering, once and ahead of time, the question the
tree-walker answers on every variable access: where does this name live?

- A **local** becomes a stack slot. A read is an index, not a lookup.
- A variable from an enclosing function becomes an **upvalue**, threaded through
  every function in between. If `c` inside `b` inside `a` uses `a`'s variable,
  `b` carries it too, even though `b` never mentions it.
- Anything else is a **global**, the one kind of access still looked up by name.

```
$ keel dis examples/closures.keel
== make_accumulator (arity 1, 0 upvalues) ==
0000    3 GET_LOCAL             1
0002    4 CLOSURE               0
0004    |   local             2
0006    | RETURN
0007    2 NIL
0008    | RETURN
```

### Closures

Captured variables follow the design in Robert Nystrom's *Crafting
Interpreters*. While a function runs, a captured variable stays on the stack and
the closure points at its slot. When the function returns, the value is moved
into a heap cell. Two closures capturing the same variable share one cell, so a
write through one is visible through the other. A block-scoped variable that was
captured is closed at the end of its block rather than simply popped.

### Dispatch

One loop over a flat list of integers. The current function's code, constants
and instruction pointer live in local variables, reloaded only on call and
return, because a local read in CPython is several times cheaper than an
attribute read. Dispatch is an `if` chain ordered by how often each instruction
actually runs.

---

## The garbage collector

Python already collects garbage, so a collector written in Python has to be
precise about what it is responsible for.

**The heap owns every Keel object.** Lists, closures and captured-variable cells
are registered when the VM creates them, and that registration keeps them alive.
The only thing that releases one is the collector deciding, from the VM's own
roots, that the program can no longer reach it. The roots are the value stack,
the call frames, the globals and the open upvalues.

**Sweeping empties the object.** That breaks cycles, so memory comes back
immediately without Python's cycle collector. The test suite proves this with
Python's collector switched off: two lists pointing at each other are reclaimed
the moment Keel's collector sweeps them.

**Use after free raises.** Every VM path that touches a heap object checks
whether it was freed. A collector that wrongly frees a live object therefore
fails loudly the moment that object is used, instead of silently returning
stale data.

**Stress mode proves the roots are complete.** It collects before every single
allocation. If any root or any reference is missing, stress mode frees a live
object almost at once and the next access raises. Every conformance program
passes under it.

**And the safety net itself is tested.** Two tests deliberately break the
collector the way real bugs do, once by not tracing a closure's captured
variables and once by leaving the globals out of the root set. Both are caught.
A test suite that only ever runs a correct collector cannot tell you the checks
work.

The next collection is scheduled when the heap has doubled since the last one,
so a program holding a large live set is not collected every few allocations.

---

## Tests

| Area | Tests |
|---|---:|
| Conformance: programs and errors across both engines and stress mode | 129 |
| Garbage collector, including the two sabotage tests | 38 |
| Lexer and parser | 24 |
| Compiler output | 13 |

```
$ .venv/bin/python -m pytest -q
204 passed in 1.25s
```

## Not built

- **Classes or maps.** Lists and closures cover the benchmarks; a dictionary type
  is the next addition.
- **`break` and `continue`.** They need a jump-patching list per loop in the
  compiler and an unwinding path in the tree-walker.
- **Generational collection.** Most objects in `garbage` die immediately, which
  is exactly the case a young generation is for.
- **Constant folding and other optimisation passes.**
- **A faster host.** The same VM design in C typically beats a tree-walker by
  much more than 3x, because the per-instruction overhead that dominates here is
  CPython's, not the design's.

## Layout

```
keel/
  lexer.py      source to tokens
  parser.py     tokens to a tree; `for` is rewritten here
  ast.py        the tree both engines start from
  runtime.py    the shared rules: truthiness, equality, arithmetic, built-ins
  treewalk.py   the tree-walking interpreter
  compiler.py   tree to bytecode: slots, upvalues, jumps
  bytecode.py   opcodes, chunks, the disassembler
  vm.py         the stack machine
  gc.py         the heap and the mark-and-sweep collector
  cli.py        run, dis, repl
bench/
  compare.py    the VM against the tree-walker
  programs/     the seven benchmark programs
tests/          204 tests
examples/       closures.keel
```
