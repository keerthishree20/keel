# Keel — Complete Project Guide

## Table of Contents
1. [What is Keel?](#what-is-keel)
2. [Quick Start](#quick-start)
3. [The Language](#the-language)
4. [Architecture](#architecture)
5. [Front End: Lexer and Parser](#front-end-lexer-and-parser)
6. [Engine 1: The Tree-Walker](#engine-1-the-tree-walker)
7. [Engine 2: Compiler and VM](#engine-2-compiler-and-vm)
8. [The Garbage Collector](#the-garbage-collector)
9. [Testing Strategy](#testing-strategy)
10. [Benchmarks](#benchmarks)
11. [Extending Keel](#extending-keel)
12. [Troubleshooting](#troubleshooting)

---

## What is Keel?

Keel is a small programming language with two complete implementations, written in pure Python:

1. **A tree-walking interpreter** that runs the parsed program directly.
2. **A bytecode compiler and stack virtual machine**, with its own mark-and-sweep garbage collector.

Both run the same language and must produce identical output. The project measures how much faster
the VM is, and explains where the difference comes from.

---

## Quick Start

Requires Python 3.10 or newer. On this machine `python3` is 3.6, so the Makefile uses `python3.12`.

```bash
make install      # .venv with test tools; Keel itself has no dependencies
make test         # conformance on both engines, the collector, the compiler, the syntax
make example      # runs examples/closures.keel on both engines
make dis          # shows its bytecode
```

The command line:

```bash
.venv/bin/python -m keel.cli run program.keel             # bytecode VM
.venv/bin/python -m keel.cli run program.keel --tree      # tree-walker
.venv/bin/python -m keel.cli run program.keel --stats     # timing and collector stats
.venv/bin/python -m keel.cli run program.keel --stress-gc # collect before every allocation
.venv/bin/python -m keel.cli dis program.keel             # disassemble
.venv/bin/python -m keel.cli repl                         # interactive prompt
```

From Python, `keel.run(source, engine="vm")` returns the printed lines as a list.

---

## The Language

```
fn make_accumulator(start) {
    let total = start;
    return fn(amount) { total = total + amount; return total; };
}
let wallet = make_accumulator(100);
wallet(25);
print(wallet(-40));      // 85
```

| feature | details |
|---|---|
| values | numbers, strings, booleans, `nil`, lists, functions |
| statements | `let`, `if` / `else`, `while`, `for`, `fn`, `return`, blocks |
| operators | `+ - * / %`, comparisons, `==`, `!=`, `!`, `and`, `or`, indexing `a[i]` |
| functions | first class, with closures |
| built-ins | `print`, `len`, `push`, `pop`, `str`, `clock` |

Rules worth knowing:
- Only `nil` and `false` are falsy. `0` and `""` are truthy.
- `true == 1` is false, even though Python says otherwise.
- Division that comes out whole stays an integer: `8 / 4` is `2`, `7 / 2` is `3.5`.
- `and` and `or` return the deciding value: `nil or "default"` is `"default"`.
- Declaring the same local twice in one scope is an error.

---

## Architecture

```
   source text
        │  lexer.py      tokenize()
        ▼
   tokens
        │  parser.py     parse()        `for` rewritten into `while` here
        ▼
   ast.Program  ───────────────┬──────────────────────────────┐
                               │                              │
                   treewalk.py │                  compiler.py │ compile_source()
                   TreeWalker  │                              ▼
                               │                     bytecode.FunctionProto
                               │                              │
                               │                        vm.py │ VM + gc.Heap
                               ▼                              ▼
                     runtime.py: truthiness, equality, arithmetic, printing, built-ins
                     (shared, so both engines follow exactly the same rules)
```

`runtime.py` is the key to a fair comparison. Neither engine decides what the language means. Both
call the same functions for truthiness, equality, arithmetic, comparison, indexing and printing.

---

## Front End: Lexer and Parser

### `keel/lexer.py`
`tokenize(source)` turns text into `Token`s with line numbers. Errors raise `KeelSyntaxError`.

### `keel/parser.py`
A recursive-descent `Parser` producing the node classes in `keel/ast.py`: expressions such as
`Binary`, `Logical`, `Call`, `Index` and `Function`, and statements such as `Let`, `If`, `While`,
`Block` and `Return`.

`for` has no node of its own. The parser rewrites it into a block holding the initialiser and a
`while` loop, so neither engine needs to know it exists.

---

## Engine 1: The Tree-Walker

`keel/treewalk.py` evaluates the tree directly.

- `Environment` is a chain of dictionaries, one per scope. Every variable access walks the chain.
- `TreeFunction` is a closure: the function node plus the environment it was created in.
- `return` is implemented by raising a Python exception, `_Return`, and catching it at the call.
- Memory is managed by Python.

This is simple and correct, and every call pays for a fresh dictionary and an exception.

---

## Engine 2: Compiler and VM

### Bytecode (`keel/bytecode.py`)
A program compiles to `FunctionProto`s, each holding a `Chunk`: a flat list of integers, constants
and line numbers. There are 37 opcodes, including:

| group | opcodes |
|---|---|
| constants and stack | `CONST`, `NIL`, `TRUE`, `FALSE`, `POP` |
| variables | `GET_LOCAL`, `SET_LOCAL`, `GET_UPVALUE`, `SET_UPVALUE`, `GET_GLOBAL`, `SET_GLOBAL`, `DEFINE_GLOBAL` |
| arithmetic and comparison | `ADD` .. `MOD`, `NEG`, `NOT`, `EQ` .. `GE` |
| control flow | `JUMP`, `JUMP_IF_FALSE`, `JUMP_IF_TRUE`, `POP_JUMP_IF_FALSE`, `LOOP` |
| functions | `CALL`, `CLOSURE`, `CLOSE_UPVALUE`, `RETURN` |
| lists | `BUILD_LIST`, `INDEX_GET`, `INDEX_SET` |

`disassemble()` prints a readable listing, which is what `keel dis` shows.

### Compiler (`keel/compiler.py`)
Its real job is deciding, once, where each name lives:
- A **local** becomes a stack slot. Reading it is an index, not a dictionary lookup.
- A variable from an enclosing function becomes an **upvalue**, threaded through every function in
  between, even ones that never mention it.
- Everything else is a **global**, the one kind of access still looked up by name.

It also emits jumps for `if` and loops and patches their targets.

### VM (`keel/vm.py`)
One dispatch loop over the integer list. The current function's code, constants and instruction
pointer live in Python local variables, reloaded only on call and return, because local reads are
much cheaper than attribute reads in CPython. The `if` chain is ordered by how often each opcode
runs. Common cases of `+`, `<`, `*`, `%` and list indexing have inline fast paths, and anything
unusual goes through `runtime.py`, so error messages stay identical to the tree-walker's.

### Closures
The design follows Robert Nystrom's *Crafting Interpreters*. While a function runs, a captured
variable stays on the stack and the closure points at its slot. When the function returns, the value
moves into a heap cell, an `ObjUpvalue`. Two closures capturing the same variable share one cell.

---

## The Garbage Collector

`keel/gc.py` holds `Heap`, `ObjClosure` and `ObjUpvalue`.

- **The heap owns every Keel object.** Lists, closures and upvalue cells are registered when the VM
  creates them, and only the collector releases them.
- **Roots** are the value stack, the call frames, the globals and the open upvalues.
- **Mark** follows references from the roots. **Sweep** empties every unmarked object, which also
  breaks reference cycles without Python's cycle collector.
- **Use after free raises `GCError`.** If the collector wrongly frees a live object, the next access
  fails loudly instead of returning stale data.
- **Scheduling.** The next collection runs when the heap has doubled since the last one.
- **Stress mode** (`--stress-gc`) collects before every allocation, which exposes any missing root
  almost immediately.

---

## Testing Strategy

| file | what it covers |
|---|---|
| `tests/programs.py` | the conformance programs and expected output, plus error programs with expected message and line |
| `tests/test_conformance.py` | every program on the tree-walker, the VM and the VM in stress mode. All three must match |
| `tests/test_gc.py` | the collector, cycles with Python's collector off, and two sabotage tests |
| `tests/test_compiler.py` | compiler output |
| `tests/test_syntax.py` | lexer and parser |

The two sabotage tests break the collector the way real bugs do, by not tracing a closure's captured
variables and by leaving globals out of the roots. Both must be caught. That proves the safety net
works, not just that a correct collector passes.

---

## Benchmarks

```bash
make bench     # the VM against the tree-walker on seven programs
```

The programs are in `bench/programs/`. Results and the explanation of each speedup are in the README.
The VM wins every program, by about 1.2 to 3 times, with function calls gaining the most.

---

## Extending Keel

### Add a built-in function
1. Add a Python function inside `make_builtins()` in `keel/runtime.py`.
2. Register it in the returned dictionary with `Builtin(name, arity, fn)`.
3. Raise `KeelRuntimeError` for bad input, so both engines report the same error.
4. Add a conformance program to `tests/programs.py`.

### Add syntax
A new statement needs a node in `ast.py`, parsing in `parser.py`, evaluation in `treewalk.py`,
compilation in `compiler.py`, and often a new opcode in `bytecode.py` handled in `vm.py`. Add
conformance programs for it, including error cases, so both engines are held to the same meaning.

### Ideas the README lists as not built
- Maps or classes.
- `break` and `continue`.
- Generational collection.
- Constant folding.

---

## Troubleshooting

### A program behaves differently on the two engines
That is a bug by definition. Add the program to `tests/programs.py` with the expected output and
fix whichever engine disagrees.

### `GCError` about a freed object
The collector released something still in use, usually a missing root or an untraced reference.
Reproduce it with `--stress-gc`, which fails much sooner.

### A redeclaration error appears at a different time on each engine
Intentional. The compiler knows every local before running, so it rejects a duplicate at compile
time. The tree-walker notices only when it reaches the second declaration.

### `python3` fails with a syntax error
The system `python3` is 3.6. Use `make install`, then run through `.venv/bin/python`.
