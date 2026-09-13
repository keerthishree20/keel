"""The garbage collector.

A collector has two ways to be wrong, and they are not equally bad. Keeping
something it could have freed is a leak. Freeing something the program can
still reach is corruption. These tests go after both, and the most important
ones deliberately break the collector to prove the safety net catches it.
"""

from __future__ import annotations

import gc as host_gc
import textwrap
import weakref

import pytest

from keel.compiler import compile_source
from keel.gc import GCError, ObjClosure, ObjUpvalue
from keel import gc as keel_gc
from keel.runtime import KList
from keel.vm import VM

from .programs import PROGRAMS


def make_vm(source: str, **kwargs) -> VM:
    vm = VM(**kwargs)
    vm.interpret(compile_source(textwrap.dedent(source)))
    return vm


# ----------------------------------------------------------------- reclaiming


def test_unreachable_lists_are_freed():
    vm = make_vm("""
        for (let i = 0; i < 5000; i = i + 1) { let garbage = [i, i, i]; }
    """)
    vm.collect()
    assert vm.heap.freed >= 5000
    # What survives is the script closure and nothing else.
    assert vm.heap.live <= 2


def test_the_heap_stays_bounded_under_sustained_garbage():
    """Without collection the heap would hold every list ever made."""
    vm = make_vm("""
        for (let i = 0; i < 50000; i = i + 1) { let garbage = [i]; }
    """)
    assert vm.heap.total_allocations > 50000
    assert vm.heap.stats()["peak_live"] < 3000, vm.heap.stats()
    assert vm.heap.collections > 0


def test_a_cycle_is_collected_with_the_host_collector_switched_off():
    """Reference counting alone can never free a cycle. This proves the Keel
    collector is what reclaims it, not Python's cycle collector: with that one
    disabled, the memory still comes back, because sweeping empties the
    objects and breaks the cycle."""
    vm = VM()
    vm.interpret(compile_source("""
        let a = [1];
        let b = [a];
        push(a, b);
    """))
    a = vm.globals["a"]
    b = vm.globals["b"]
    assert a.items[1] is b and b.items[0] is a
    probe_a, probe_b = weakref.ref(a), weakref.ref(b)
    del a, b

    host_gc.disable()
    try:
        del vm.globals["a"], vm.globals["b"]
        freed = vm.collect()
        assert freed >= 2
        assert probe_a() is None and probe_b() is None, "the cycle was not reclaimed"
    finally:
        host_gc.enable()


def test_a_closure_that_captured_itself_is_collected():
    vm = make_vm("""
        let holder = nil;
        {
            let me = nil;
            me = fn() { return me; };
            holder = me;
        }
    """)
    closure = vm.globals["holder"]
    assert type(closure) is ObjClosure
    probe = weakref.ref(closure)
    del closure
    host_gc.disable()
    try:
        vm.globals["holder"] = None
        vm.collect()
        assert probe() is None
    finally:
        host_gc.enable()


# ------------------------------------------------------------------- keeping


def test_everything_reachable_from_a_global_survives():
    vm = make_vm("""
        let keep = [[1, 2], [3, [4, 5]]];
    """)
    # The first collection frees the finished script's own closure: once the
    # program returns, nothing references it. After that the live set is exactly
    # the four lists, and repeated collections must not shrink it further.
    vm.collect()
    assert vm.heap.live == 4
    vm.collect()
    vm.collect()
    assert vm.heap.live == 4
    assert vm.globals["keep"].items[1].items[1].items == [4, 5]


def test_values_captured_by_a_closure_survive_their_function():
    vm = make_vm("""
        fn make() {
            let data = [10, 20, 30];
            return fn() { return data; };
        }
        let getter = make();
    """)
    vm.collect()
    getter = vm.globals["getter"]
    upvalue = getter.upvalues[0]
    assert type(upvalue) is ObjUpvalue and upvalue.slot == -1
    assert not upvalue.value.freed
    assert upvalue.value.items == [10, 20, 30]


@pytest.mark.parametrize("name", PROGRAMS)
def test_stress_mode_never_frees_a_live_object(name):
    """The collector runs before every allocation. Any missing root or missing
    reference frees something live straight away, and the VM's freed-object
    checks turn that into a GCError instead of wrong output."""
    source, expected = PROGRAMS[name]
    vm = VM(stress_gc=True)
    vm.interpret(compile_source(textwrap.dedent(source)))
    assert vm.output == expected
    if vm.heap.total_allocations:
        assert vm.heap.collections >= vm.heap.total_allocations


# ------------------------------------------------ the safety net, proven to work


def test_forgetting_to_trace_closure_upvalues_is_caught(monkeypatch):
    """Sabotage the collector the way a real bug would, and check the damage is
    detected rather than silently producing garbage."""
    real_trace = keel_gc._trace

    def broken_trace(obj, mark):
        if type(obj) is ObjClosure:
            return            # the bug: a closure's captured variables are never marked
        real_trace(obj, mark)

    monkeypatch.setattr(keel_gc, "_trace", broken_trace)
    with pytest.raises(GCError, match="already freed"):
        make_vm("""
            fn make() { let n = [0]; return fn() { return n; }; }
            let f = make();
            let pressure = [1, 2, 3];
            print(f());
        """, stress_gc=True)


def test_forgetting_a_root_is_caught(monkeypatch):
    """The other classic bug: a root set that misses the globals."""
    def roots_without_globals(self, mark):
        for value in self.stack:
            mark(value)
        for frame in self.frames:
            mark(frame.closure)

    monkeypatch.setattr(VM, "mark_roots", roots_without_globals)
    with pytest.raises(GCError, match="already freed"):
        make_vm("""
            let kept = [1, 2, 3];
            let pressure = [4];
            print(kept[0]);
        """, stress_gc=True)


def test_building_a_list_roots_its_items_during_collection():
    """BUILD_LIST registers the new list while its items are still on the stack.
    If the order were reversed, a collection at that moment would free items
    that are about to be stored."""
    vm = make_vm("""
        let nested = [[1], [2], [3], [4]];
        print(nested);
    """, stress_gc=True)
    assert vm.output == ["[[1], [2], [3], [4]]"]


# -------------------------------------------------------------------- stats


def test_stats_describe_the_run():
    vm = make_vm("for (let i = 0; i < 3000; i = i + 1) { let g = [i]; }")
    stats = vm.heap.stats()
    assert stats["allocations"] > 3000
    assert stats["collections"] >= 1
    assert stats["freed"] > 0
    assert stats["pause_max_ms"] >= 0
    assert stats["stress"] is False


def test_the_threshold_grows_with_the_live_set():
    """Collect when the heap has doubled. A program holding a large live set
    should not be collected every few allocations."""
    vm = make_vm("""
        let big = [];
        for (let i = 0; i < 6000; i = i + 1) push(big, [i]);
    """)
    assert vm.heap.collections < 20, vm.heap.stats()


def test_stress_mode_is_much_slower_and_says_why():
    vm = make_vm("for (let i = 0; i < 300; i = i + 1) { let g = [i]; }", stress_gc=True)
    assert vm.heap.collections >= 300
