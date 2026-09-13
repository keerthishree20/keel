"""Command line interface.

    keel run program.keel               run on the bytecode VM
    keel run program.keel --tree        run on the tree-walker
    keel run program.keel --stats       print collector statistics afterwards
    keel run program.keel --stress-gc   collect before every allocation
    keel dis program.keel               show the compiled bytecode
    keel repl                           read, evaluate, print
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

from .lexer import KeelSyntaxError
from .runtime import KeelRuntimeError


def _source(path: str) -> str:
    try:
        return pathlib.Path(path).read_text()
    except OSError as exc:
        raise SystemExit(f"cannot read {path}: {exc.strerror}") from None


def cmd_run(args) -> int:
    from .parser import parse
    source = _source(args.file)
    started = time.perf_counter()
    try:
        program = parse(source)
        if args.tree:
            from .treewalk import TreeWalker
            TreeWalker(out=print).run(program)
            stats = None
        else:
            from .compiler import Compiler
            from .vm import VM
            vm = VM(out=print, stress_gc=args.stress_gc)
            vm.interpret(Compiler().compile_program(program))
            stats = vm.heap.stats()
    except KeelSyntaxError as exc:
        print(f"{args.file}: syntax error, {exc}", file=sys.stderr)
        return 65
    except KeelRuntimeError as exc:
        print(f"{args.file}: runtime error, {exc}", file=sys.stderr)
        return 70
    elapsed = time.perf_counter() - started
    if args.stats:
        report = {"engine": "tree" if args.tree else "vm", "seconds": round(elapsed, 4)}
        if stats:
            report["gc"] = stats
        print(json.dumps(report, indent=2), file=sys.stderr)
    return 0


def cmd_dis(args) -> int:
    from .bytecode import disassemble
    from .compiler import compile_source
    try:
        print(disassemble(compile_source(_source(args.file))))
    except KeelSyntaxError as exc:
        print(f"{args.file}: syntax error, {exc}", file=sys.stderr)
        return 65
    return 0


def cmd_repl(args) -> int:
    """Each line is compiled and run against one persistent set of globals."""
    from .compiler import compile_source
    from .vm import VM
    vm = VM(out=print)
    print("keel repl. Ctrl-D to leave.")
    while True:
        try:
            line = input("> ")
        except EOFError:
            print()
            return 0
        if not line.strip():
            continue
        if not line.rstrip().endswith((";", "}")):
            line = f"print({line});"
        try:
            vm.interpret(compile_source(line))
        except (KeelSyntaxError, KeelRuntimeError) as exc:
            print(f"error: {exc}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="keel", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="run a program")
    p.add_argument("file")
    p.add_argument("--tree", action="store_true", help="use the tree-walking interpreter")
    p.add_argument("--stats", action="store_true", help="report timing and collector stats")
    p.add_argument("--stress-gc", action="store_true", help="collect before every allocation")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("dis", help="disassemble a program")
    p.add_argument("file")
    p.set_defaults(fn=cmd_dis)

    sub.add_parser("repl", help="interactive prompt").set_defaults(fn=cmd_repl)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
