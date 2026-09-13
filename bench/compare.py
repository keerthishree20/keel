"""Bytecode VM against the tree-walker, on the same programs.

Each program runs in both engines, their output is compared first (a speedup on
different answers means nothing), and then each is timed several times with the
median kept. Parsing is shared and excluded from both. Compilation is timed
separately and added to the VM's total, because a VM that is fast only after a
slow compile has not really won on short programs.

    python -m bench.compare --repeat 5
"""

from __future__ import annotations

import argparse
import gc
import json
import pathlib
import statistics
import time

from keel.compiler import Compiler
from keel.parser import parse
from keel.treewalk import TreeWalker
from keel.vm import VM

HERE = pathlib.Path(__file__).resolve().parent


def time_tree(program) -> tuple[float, list[str]]:
    walker = TreeWalker()
    started = time.perf_counter()
    walker.run(program)
    return time.perf_counter() - started, walker.output


def time_vm(program, *, stress_gc: bool = False) -> tuple[float, float, list[str], dict]:
    started = time.perf_counter()
    proto = Compiler().compile_program(program)
    compile_s = time.perf_counter() - started
    vm = VM(stress_gc=stress_gc)
    started = time.perf_counter()
    vm.interpret(proto)
    return compile_s, time.perf_counter() - started, vm.output, vm.heap.stats()


def median_of(repeat: int, fn):
    results = []
    for _ in range(repeat):
        gc.collect()
        results.append(fn())
    return results


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="bench.compare", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repeat", type=int, default=5)
    p.add_argument("--only", default=None, help="comma separated program names")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    files = sorted((HERE / "programs").glob("*.keel"))
    if args.only:
        wanted = set(args.only.split(","))
        files = [f for f in files if f.stem in wanted]

    rows = []
    for path in files:
        program = parse(path.read_text())

        tree_runs = median_of(args.repeat, lambda: time_tree(program))
        vm_runs = median_of(args.repeat, lambda: time_vm(program))
        tree_out = tree_runs[0][1]
        vm_out = vm_runs[0][2]
        if tree_out != vm_out:
            raise SystemExit(f"{path.stem}: engines disagree, {tree_out} against {vm_out}")

        tree_s = statistics.median(r[0] for r in tree_runs)
        compile_s = statistics.median(r[0] for r in vm_runs)
        vm_s = statistics.median(r[1] for r in vm_runs)
        heap = vm_runs[-1][3]
        rows.append({
            "program": path.stem,
            "output": vm_out,
            "tree_ms": round(tree_s * 1000, 1),
            "vm_ms": round(vm_s * 1000, 1),
            "compile_ms": round(compile_s * 1000, 2),
            "speedup": round(tree_s / (vm_s + compile_s), 2),
            "gc_collections": heap["collections"],
            "gc_freed": heap["freed"],
            "gc_pause_total_ms": heap["pause_total_ms"],
            "gc_pause_max_ms": heap["pause_max_ms"],
        })
        print(f"measured {path.stem}", flush=True, file=__import__("sys").stderr)

    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    print(f"\nmedian of {args.repeat} runs, parsing excluded, compile time charged to the VM\n")
    print(f"{'program':<14} {'tree':>10} {'vm':>10} {'compile':>9} {'speedup':>8} "
          f"{'gc runs':>8} {'freed':>9} {'gc total':>10}")
    for r in rows:
        print(f"{r['program']:<14} {r['tree_ms']:>8.1f}ms {r['vm_ms']:>8.1f}ms "
              f"{r['compile_ms']:>7.2f}ms {r['speedup']:>7.2f}x "
              f"{r['gc_collections']:>8} {r['gc_freed']:>9,} {r['gc_pause_total_ms']:>8.1f}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
