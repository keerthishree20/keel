# Keel — Complete Project Guide

A complete guide from zero to a working programming language with two interpreters and a garbage
collector. Covers every feature, every design decision and the reason behind it, with the real code.
It is self-contained: you can paste it into any AI chat and ask questions about the project without
sharing the repository.

**Repository:** https://github.com/keerthishree20/keel

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Tech Stack & Why](#2-tech-stack--why)
3. [Project Setup from Scratch](#3-project-setup-from-scratch)
4. [The Keel Language](#4-the-keel-language)
5. [Core Ideas in Plain Words](#5-core-ideas-in-plain-words)
6. [Project Structure](#6-project-structure)
7. [Lexer: Text to Tokens](#7-lexer-text-to-tokens)
8. [Parser: Tokens to a Tree](#8-parser-tokens-to-a-tree)
9. [Shared Runtime Rules](#9-shared-runtime-rules)
10. [Engine 1: The Tree-Walker](#10-engine-1-the-tree-walker)
11. [Bytecode](#11-bytecode)
12. [The Compiler: Where Does Each Name Live?](#12-the-compiler-where-does-each-name-live)
13. [Closures and Upvalues](#13-closures-and-upvalues)
14. [Engine 2: The Virtual Machine](#14-engine-2-the-virtual-machine)
15. [The Garbage Collector](#15-the-garbage-collector)
16. [Stress Mode and Sabotage Tests](#16-stress-mode-and-sabotage-tests)
17. [Built-in Functions](#17-built-in-functions)
18. [Command Line](#18-command-line)
19. [Testing](#19-testing)
20. [Benchmarks & Results](#20-benchmarks--results)
21. [Extending Keel](#21-extending-keel)
22. [Deliberately Not Built](#22-deliberately-not-built)
23. [Troubleshooting](#23-troubleshooting)
24. [Complete Feature Summary](#24-complete-feature-summary)

---

## 1. Project Overview

Keel is a **small programming language** with two complete implementations, written in pure Python:

1. a **tree-walking interpreter** that runs the parsed program directly, and
2. a **bytecode compiler and stack virtual machine** with its own **mark-and-sweep garbage collector**.

Both run exactly the same language and must print exactly the same output. The project measures how
much faster the VM is, and explains where every bit of the difference comes from.

```
fn make_accumulator(start) {
    let total = start;
    return fn(amount) { total = total + amount; return total; };
}
let wallet = make_accumulator(100);
wallet(25);
print(wallet(-40));      // 85
```

**Status:** complete. 204 tests pass. The VM is 1.2 to 3 times faster than the tree-walker.

---

## 2. Tech Stack & Why

| Technology | Role | Why We Chose It |
|---|---|---|
| **Python 3.10+** | Host language | readable, so both engines can be compared line by line |
| **Standard library only** | Runtime | the point is building a language, not using a parser library |
| **Recursive-descent parser** | Parsing | hand-written, easy to follow, one function per grammar rule |
| **Flat integer list** | Bytecode | fastest thing to index in CPython |
| **Mark-and-sweep** | Garbage collection | simplest correct collector, easy to reason about |
| **pytest** | Tests | every program runs three ways and must match |

---

## 3. Project Setup from Scratch

```bash
git clone https://github.com/keerthishree20/keel.git
cd keel
make install      # .venv with test tools (python3.12; python3 here is 3.6)
make test         # all 204 tests, about 1 second
make example      # runs examples/closures.keel on both engines
make dis          # shows its bytecode
make bench        # the VM against the tree-walker
```

Run your own program:
```bash
.venv/bin/python -m keel.cli run program.keel             # bytecode VM
.venv/bin/python -m keel.cli run program.keel --tree      # tree-walker
.venv/bin/python -m keel.cli run program.keel --stats     # timing and collector stats
.venv/bin/python -m keel.cli run program.keel --stress-gc # collect before every allocation
.venv/bin/python -m keel.cli dis program.keel             # show bytecode
.venv/bin/python -m keel.cli repl                         # interactive prompt
```

From Python: `keel.run(source, engine="vm")` returns the printed lines as a list.

---

## 4. The Keel Language

| Feature | Details |
|---|---|
| Values | numbers, strings, booleans, `nil`, lists, functions |
| Declarations | `let x = 1;` and `fn name(a, b) { ... }` |
| Control flow | `if` / `else`, `while`, `for`, `return`, blocks `{ }` |
| Operators | `+ - * / %`, `< <= > >= == !=`, `!`, `and`, `or`, `-x` |
| Lists | `[1, 2, 3]`, indexing `a[0]`, assignment `a[0] = 5` |
| Functions | first class, anonymous `fn(x) { ... }`, closures |
| Built-ins | `print`, `len`, `push`, `pop`, `str`, `clock` |

### Rules worth knowing
- Only `nil` and `false` are falsy. `0` and `""` are **truthy**.
- `true == 1` is **false**, even though Python says otherwise.
- Whole division stays an integer: `8 / 4` is `2`; `7 / 2` is `3.5`.
- `and` and `or` return the deciding value: `nil or "default"` gives `"default"`.
- Declaring the same local twice in one scope is an error.
- `for` has no implementation of its own; the parser rewrites it (section 8).

### Example program
```
fn fib(n) {
    if (n < 2) return n;
    return fib(n - 1) + fib(n - 2);
}
let squares = [];
for (let i = 0; i < 5; i = i + 1) {
    push(squares, i * i);
}
print(fib(20));        // 6765
print(squares);        // [0, 1, 4, 9, 16]
```

---

## 5. Core Ideas in Plain Words

| Idea | Meaning |
|---|---|
| **Lexer** | splits source text into tokens like `let`, `x`, `=`, `5` |
| **Parser** | builds a tree (AST) that shows the structure of the program |
| **Tree-walker** | runs the program by visiting tree nodes one by one |
| **Bytecode** | a compact list of simple instructions, like `GET_LOCAL 1`, `ADD` |
| **Compiler** | turns the tree into bytecode once, before running |
| **Virtual machine** | a loop that runs bytecode instructions on a stack |
| **Closure** | a function plus the variables it captured from where it was created |
| **Upvalue** | one captured variable inside a closure |
| **Garbage collector** | frees objects the program can no longer reach |

---

## 6. Project Structure

```
keel/
  lexer.py      tokenize(): source to tokens, KeelSyntaxError
  parser.py     Parser: tokens to a tree; `for` is rewritten here
  ast.py        the tree node classes both engines start from
  runtime.py    shared rules: truthiness, equality, arithmetic, printing, built-ins
  treewalk.py   TreeWalker: the tree-walking interpreter
  bytecode.py   37 opcodes, Chunk, FunctionProto, the disassembler
  compiler.py   Compiler: tree to bytecode (slots, upvalues, jumps)
  vm.py         VM: the stack machine
  gc.py         Heap, ObjClosure, ObjUpvalue: the collector
  cli.py        run, dis, repl
  __init__.py   keel.run(source, engine=)
bench/
  compare.py    the VM against the tree-walker
  programs/     the 7 benchmark programs
tests/
  programs.py          conformance programs and expected output, plus error programs
  test_conformance.py  every program on 3 engines
  test_gc.py           the collector and sabotage tests
  test_compiler.py     compiler output
  test_syntax.py       lexer and parser
examples/closures.keel
```

### The pipeline
```
source ──► lexer ──► tokens ──► parser ──► AST ──┬──► tree-walker ─┐
                                                 └──► compiler ──► bytecode ──► VM + GC
                                                                    │
                           both use runtime.py for every language rule
```

---

## 7. Lexer: Text to Tokens

`tokenize(source)` in `keel/lexer.py` turns text into `Token`s, each with its kind, text and line
number. It handles numbers, strings, identifiers, keywords, operators and `//` comments. Anything it
does not understand raises `KeelSyntaxError` with the line and column.

---

## 8. Parser: Tokens to a Tree

`keel/parser.py` is a **recursive-descent parser**: one method per grammar rule, from lowest
precedence (`or`) to highest (calls and indexing). It produces the node classes in `keel/ast.py`:

| Expressions | Statements |
|---|---|
| `Literal`, `Name`, `Assign`, `Unary`, `Binary`, `Logical`, `Call`, `ListLiteral`, `Index`, `IndexAssign`, `Function` | `ExprStmt`, `Let`, `FnDecl`, `Block`, `If`, `While`, `Return` |

### `for` is rewritten
There is no `For` node. The parser turns
```
for (let i = 0; i < 5; i = i + 1) { body }
```
into
```
{ let i = 0; while (i < 5) { body  i = i + 1; } }
```
so neither engine needs to know `for` exists.

---

## 9. Shared Runtime Rules

A speed comparison between two interpreters means nothing if they disagree about what programs mean.
So **neither engine decides the rules.** `keel/runtime.py` holds them, and both engines call it.

```python
def truthy(value) -> bool:
    return not (value is None or value is False)

def equal(a, b) -> bool:
    if is_number(a) and is_number(b):
        return a == b
    if type(a) is not type(b):
        return False                # so true == 1 is false
    if isinstance(a, KList):
        return a is b               # lists compare by identity
    return a == b

def arithmetic(op, a, b, line):
    if op == "+":
        if is_number(a) and is_number(b):
            return a + b
        if type(a) is str and type(b) is str:
            return a + b
        raise KeelRuntimeError(f"cannot add {type_name(a)} and {type_name(b)}", line)
    ...
    if op == "/":
        if b == 0:
            raise KeelRuntimeError("division by zero", line)
        result = a / b
        return int(result) if type(a) is int and type(b) is int and a % b == 0 else result
```

Also shared: `compare`, `negate`, `index_get`, `index_set`, `stringify` (how values print), and
`make_builtins`. Error messages come from here too, so both engines report the same message on the
same line.

---

## 10. Engine 1: The Tree-Walker

`keel/treewalk.py` evaluates the tree directly.

- **`Environment`** is a chain of dictionaries, one per scope. Every variable access walks up the
  chain until it finds the name.
- **`TreeFunction`** is a closure: the function node plus the environment it was created in.
- **`return`** raises a Python exception, `_Return`, which the call catches.
- Memory is left to Python.

It is simple and obviously correct. The cost: every call builds a new dictionary and uses an
exception to return, and every variable read is a dictionary lookup.

---

## 11. Bytecode

`keel/bytecode.py`. A program compiles to `FunctionProto`s, each holding a `Chunk`: a flat list of
integers (opcodes followed by their operands), a list of constants, and line numbers.

| Group | Opcodes |
|---|---|
| constants and stack | `CONST`, `NIL`, `TRUE`, `FALSE`, `POP` |
| variables | `GET_LOCAL`, `SET_LOCAL`, `GET_UPVALUE`, `SET_UPVALUE`, `GET_GLOBAL`, `SET_GLOBAL`, `DEFINE_GLOBAL` |
| arithmetic | `ADD`, `SUB`, `MUL`, `DIV`, `MOD`, `NEG`, `NOT` |
| comparison | `EQ`, `NEQ`, `LT`, `LE`, `GT`, `GE` |
| control flow | `JUMP`, `JUMP_IF_FALSE`, `JUMP_IF_TRUE`, `POP_JUMP_IF_FALSE`, `LOOP` |
| functions | `CALL`, `CLOSURE`, `CLOSE_UPVALUE`, `RETURN` |
| lists | `BUILD_LIST`, `INDEX_GET`, `INDEX_SET` |

37 opcodes in total. `disassemble()` prints a readable listing:

```
$ keel dis examples/closures.keel
== make_accumulator (arity 1, 0 upvalues) ==
0000    3 GET_LOCAL             1
0002    4 CLOSURE               0
0004    |   local             2
0006    | RETURN
```

---

## 12. The Compiler: Where Does Each Name Live?

`keel/compiler.py`. Its real job is answering, **once and ahead of time**, the question the
tree-walker answers on every single variable access: where does this name live?

```python
def variable(self, name, line, *, assign):
    slot = self.resolve_local(self.state, name)
    if slot != -1:
        self.emit(op.SET_LOCAL if assign else op.GET_LOCAL, slot, line)      # a stack slot
        return
    upvalue = self.resolve_upvalue(self.state, name)
    if upvalue != -1:
        self.emit(op.SET_UPVALUE if assign else op.GET_UPVALUE, upvalue, line)  # captured
        return
    self.emit(op.SET_GLOBAL if assign else op.GET_GLOBAL, self.chunk.constant(name), line)
```

| Kind | How it is read |
|---|---|
| **Local** | a stack slot: reading it is an index, not a lookup |
| **Upvalue** | a variable from an enclosing function, captured by the closure |
| **Global** | the only kind still looked up by name, in a dictionary |

### Scopes
`begin_scope()` and `end_scope()` track block nesting. When a block ends, each local is popped, or,
if a closure captured it, hoisted off the stack with `CLOSE_UPVALUE`:

```python
while state.locals and state.locals[-1].depth > state.scope_depth:
    self.emit(op.CLOSE_UPVALUE if state.locals[-1].captured else op.POP, line)
    state.locals.pop()
```

`add_local` rejects a duplicate name in the same scope, and more than 256 locals in one function.

### Jumps
`emit_jump` writes a placeholder, and `patch_jump` fills in the distance once the target is known.
`emit_loop` jumps backwards for `while`.

---

## 13. Closures and Upvalues

The design follows Robert Nystrom's *Crafting Interpreters*.

### Finding a captured variable
```python
def resolve_upvalue(self, state, name):
    if state.enclosing is None:
        return -1
    slot = self.resolve_local(state.enclosing, name)
    if slot != -1:
        state.enclosing.locals[slot].captured = True
        return self.add_upvalue(state, True, slot)       # parent's local
    outer = self.resolve_upvalue(state.enclosing, name)
    if outer != -1:
        return self.add_upvalue(state, False, outer)     # parent's upvalue
    return -1
```

If `c` inside `b` inside `a` uses `a`'s variable, `b` carries it too, even though `b` never mentions
it. Each function only ever reaches its direct parent.

### Open and closed upvalues
- While the function that owns a variable is still running, the variable stays **on the stack**, and
  the closure points at its slot (an *open* upvalue).
- When that function returns, or the block ends, the value moves into a heap cell, an `ObjUpvalue`
  (now *closed*).
- Two closures capturing the same variable share **one** cell, so a write through one is seen by the
  other.

---

## 14. Engine 2: The Virtual Machine

`keel/vm.py` runs one loop over the integer list:

```python
def run(self) -> None:
    stack = self.stack
    frame = frames[-1]
    code = frame.closure.function.chunk.code
    consts = frame.closure.function.chunk.constants
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
                stack[-1] = a + b                        # fast path
            else:
                stack[-1] = arithmetic("+", a, b, lines[ip - 1])   # shared rules
        ...
```

### Speed tricks, and why
- **Local variables for `code`, `consts`, `ip`, `base`.** In CPython, reading a local is several times
  cheaper than reading an attribute. They are reloaded only on call and return.
- **The `if` chain is ordered by how often each instruction runs**, so the common ones match first.
- **Fast paths** for integer `+`, `<`, `*`, `%` and list indexing. Anything unusual, including every
  error, goes through `runtime.py`, so messages stay identical to the tree-walker.
- **Calls push a frame; return is a jump.** No dictionaries, no exceptions.

---

## 15. The Garbage Collector

Python already collects garbage, so a collector written in Python has to be precise about what it is
responsible for.

**The heap owns every Keel object.** Lists, closures and upvalue cells are registered when the VM
creates them, and only the collector releases them.

```python
def register(self, vm, obj):
    if self.stress or self.allocations_since >= self.threshold:
        self.collect(vm)                  # collect BEFORE registering the new object
    self.objects.append(obj)
    self.allocations_since += 1

def collect(self, vm):
    gray = []
    def mark(value):
        if type(value) in _HEAP_TYPES and not value.marked:
            if value.freed:
                raise GCError("marking an object that was already freed")
            value.marked = True
            gray.append(value)
    vm.mark_roots(mark)                   # start from the roots
    while gray:
        _trace(gray.pop(), mark)          # follow references
    survivors = []
    for obj in self.objects:
        if obj.marked:
            obj.marked = False
            survivors.append(obj)
        else:
            _release(obj)                 # empty it: breaks cycles immediately
    self.objects = survivors
    self.threshold = max(MIN_THRESHOLD, len(survivors) * 2)   # next time the heap doubles
```

### The roots
```python
def mark_roots(self, mark):
    for value in self.stack:            mark(value)
    for frame in self.frames:           mark(frame.closure)
    for value in self.globals.values(): mark(value)
    for upvalue in self.open_upvalues.values(): mark(upvalue)
```

### Design points
- **Sweeping empties the object**, which breaks reference cycles without Python's cycle collector. A
  test proves it with Python's collector switched off.
- **Use after free raises `GCError`.** If the collector wrongly frees a live object, the next access
  fails loudly instead of returning stale data.
- **Scheduling:** collect again when the heap has doubled, so a program with a big live set is not
  collected every few allocations.
- `--stats` shows allocations, collections, freed, live, peak, and total and maximum pause.

---

## 16. Stress Mode and Sabotage Tests

**Stress mode** (`--stress-gc`) collects before **every single allocation**. If any root or any
reference is missing, a live object is freed almost at once and the next access raises. Every
conformance program passes under it.

**Sabotage tests** break the collector the way real bugs do:
1. not tracing a closure's captured variables,
2. leaving the globals out of the root set.

Both must be caught. A suite that only ever runs a correct collector cannot tell you the checks work.

---

## 17. Built-in Functions

Defined in `make_builtins()` in `runtime.py`:

| Built-in | Arity | Does |
|---|---|---|
| `print(x)` | 1 | prints the value |
| `len(x)` | 1 | length of a list or string |
| `push(list, x)` | 2 | append to a list |
| `pop(list)` | 1 | remove and return the last item; error if empty |
| `str(x)` | 1 | the value as a string |
| `clock()` | 0 | seconds, for timing programs |

---

## 18. Command Line

```
keel run <file> [--tree] [--stats] [--stress-gc]
keel dis <file>
keel repl
```

---

## 19. Testing

Every conformance program runs **three ways** (tree-walker, VM, VM in stress mode) and all three must
print exactly the expected lines. Sixteen programs that must fail do so with the same message on the
same line in both engines.

| Area | Tests |
|---|---:|
| Conformance: programs and errors across both engines and stress mode | 129 |
| Garbage collector, including the two sabotage tests | 38 |
| Lexer and parser | 24 |
| Compiler output | 13 |

### The one intentional difference
Declaring the same local twice in a scope is an error in both engines, but the compiler knows every
local before running and rejects it **at compile time**, while the tree-walker only notices when it
reaches the second declaration. It has a test of its own.

```bash
make test
```

---

## 20. Benchmarks & Results

Median of five runs per program. Parsing excluded from both; compile time charged to the VM (under
0.2 ms for every program). Intel Core i5-11320H, Python 3.12. Reproduce with `make bench`.

| Program | What it stresses | Tree-walker | VM | Speedup |
|---|---|---:|---:|---:|
| `fib` | function calls | 1,336 ms | 447 ms | **2.99×** |
| `loop_locals` | loop over local variables | 2,423 ms | 1,150 ms | **2.11×** |
| `nested` | nested loops with a call inside | 1,167 ms | 581 ms | **2.01×** |
| `closures` | captured variables | 1,304 ms | 731 ms | **1.78×** |
| `loop_globals` | the same loop over globals | 2,430 ms | 1,425 ms | **1.71×** |
| `lists` | building and indexing | 1,205 ms | 757 ms | **1.59×** |
| `garbage` | allocation pressure | 1,208 ms | 1,031 ms | **1.17×** |

### Where the speedup comes from
- **Calls, most of all.** `fib` gains most: the tree-walker builds a dictionary and throws an exception
  per call; the VM pushes a frame and jumps.
- **Knowing where variables live.** `loop_locals` (2.11×) against `loop_globals` (1.71×) is the same
  loop; the difference, about 23%, is what compile-time slot resolution is worth.
- **Allocation gains least.** In `garbage`, collection pauses total only 54 ms; the cost is owning
  every object at all: registering it and sweeping it.

### The fast paths, measured separately
| Program | Before fast paths | After |
|---|---:|---:|
| `garbage` | 1.04× | 1.17× |
| `loop_locals` | 1.93× | 2.11× |
| `nested` | 1.82× | 2.01× |
| `fib` | 2.95× | 2.99× |

Most of the speedup is the architecture; about a tenth, on arithmetic-heavy programs, is the tuning.

---

## 21. Extending Keel

### Add a built-in
1. Add a Python function inside `make_builtins()` in `keel/runtime.py`.
2. Register it: `Builtin(name, arity, fn)`.
3. Raise `KeelRuntimeError` for bad input so both engines report the same error.
4. Add a conformance program to `tests/programs.py`.

### Add syntax
A new statement needs: a node in `ast.py`, parsing in `parser.py`, evaluation in `treewalk.py`,
compilation in `compiler.py`, often a new opcode in `bytecode.py` handled in `vm.py`, and conformance
programs including error cases.

---

## 22. Deliberately Not Built

| Feature | Why not |
|---|---|
| classes or maps | lists and closures cover the benchmarks; a dictionary type is next |
| `break` and `continue` | need jump-patching per loop and an unwinding path in the tree-walker |
| generational collection | most objects in `garbage` die young, exactly what it is for |
| constant folding and optimisation passes | out of scope |
| a faster host | the same VM design in C beats a tree-walker by far more than 3× |

---

## 23. Troubleshooting

### A program behaves differently on the two engines
That is a bug by definition. Add it to `tests/programs.py` with the expected output and fix whichever
engine disagrees.

### `GCError` about a freed object
The collector released something still in use: a missing root or an untraced reference. Reproduce with
`--stress-gc`, which fails much sooner.

### A redeclaration error appears at a different time on each engine
Intentional (section 19).

### `python3` fails with a syntax error
The system `python3` is 3.6. Use `make install` and `.venv/bin/python`.

---

## 24. Complete Feature Summary

### All Features Built

| # | Feature | Type | Key Files |
|---|---|---|---|
| 1 | Lexer with line numbers | Front end | `lexer.py` |
| 2 | Recursive-descent parser, `for` desugaring | Front end | `parser.py`, `ast.py` |
| 3 | Shared language rules and built-ins | Runtime | `runtime.py` |
| 4 | Tree-walking interpreter | Engine | `treewalk.py` |
| 5 | Bytecode format and disassembler | Engine | `bytecode.py` |
| 6 | Compiler with slot and upvalue resolution | Engine | `compiler.py` |
| 7 | Closures with shared upvalue cells | Engine | `compiler.py`, `vm.py`, `gc.py` |
| 8 | Stack VM with fast paths | Engine | `vm.py` |
| 9 | Mark-and-sweep collector | Memory | `gc.py` |
| 10 | Stress mode and use-after-free detection | Memory | `gc.py`, `vm.py` |
| 11 | CLI: run, dis, repl, stats | Tooling | `cli.py` |
| 12 | Three-way conformance tests | Testing | `tests/` |
| 13 | Collector sabotage tests | Testing | `tests/test_gc.py` |
| 14 | VM vs tree-walker benchmark | Tooling | `bench/` |

### Data Flow Architecture

```
source text
  └── tokenize() ──► Parser ──► ast.Program
        ├── TreeWalker.run()
        │     Environment chain lookups, _Return exceptions, Python memory
        └── Compiler.compile_program()
              locals ──► stack slots, captured ──► upvalues, rest ──► globals
              └── FunctionProto(Chunk: code ints, constants, lines)
                    └── VM.run()
                          fast paths ──► runtime.py for everything unusual
                          new list / closure / upvalue ──► Heap.register()
                                └── collect(): mark from roots, sweep, threshold = 2 × live

Both engines ──► runtime.py (truthy, equal, arithmetic, compare, stringify, built-ins)
```

### Tech Stack at a Glance

```
Language:   Python 3.10+ (standard library only)
Front end:  hand-written lexer, recursive-descent parser
Engines:    tree-walking interpreter; bytecode compiler + stack VM
Memory:     mark-and-sweep GC with stress mode
Testing:    pytest, 3-way conformance, sabotage tests
Reference:  Crafting Interpreters (Robert Nystrom) for closures and upvalues
```
