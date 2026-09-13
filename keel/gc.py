"""The heap and a mark-and-sweep collector.

Python already has a garbage collector, so a collector written in Python needs
a clear statement of what it is actually responsible for.

**The heap owns every Keel object.** Lists, closures and captured-variable
cells are registered here when the VM creates them, and that registration is a
strong reference: nothing the Keel program does can make one go away. The only
thing that releases an object is this collector deciding, from the VM's own
roots, that the program can no longer reach it.

When it sweeps an object it also empties it. That does two jobs. It breaks
cycles, so the host's reference counting can reclaim the memory immediately
without waiting on Python's own cycle collector; the tests prove this with
Python's collector switched off. And it makes a collector bug loud: every VM
path that touches a heap object checks the `freed` flag, so an object swept
while still reachable raises at the moment it is used, instead of quietly
returning stale data.

Stress mode collects before every single allocation. It is slow and it exists
for exactly one purpose: if any root is missing from `mark_roots`, or any
reference is missing from `trace`, stress mode frees something live almost
immediately, and the next use of it fails the test suite.
"""

from __future__ import annotations

import time

from .runtime import KeelRuntimeError, KList

MIN_THRESHOLD = 1024


class GCError(KeelRuntimeError):
    """A live object was swept. Always a bug in the collector, never in the program."""


class Heap:
    def __init__(self, *, stress: bool = False, threshold: int = MIN_THRESHOLD):
        self.objects: list = []
        self.stress = stress
        self.threshold = threshold
        self.allocations_since = 0

        self.allocations = 0
        self.collections = 0
        self.freed = 0
        self.pause_total_s = 0.0
        self.pause_max_s = 0.0
        self.peak_live = 0

    def register(self, vm, obj) -> None:
        """Take ownership of a new object, collecting first if it is time.

        The collection happens before the new object is registered, so the
        caller must make sure anything the object refers to is already
        reachable from a root. The VM does: list items are still on the stack
        while the list is created, and a closure is pushed onto the stack before
        its captured variables are allocated.
        """
        if self.stress or self.allocations_since >= self.threshold:
            self.collect(vm)
        self.objects.append(obj)
        self.allocations_since += 1

    def collect(self, vm) -> int:
        started = time.perf_counter()
        # Totals are brought up to date here rather than on every allocation. The
        # heap is at its largest just before a sweep, so this is also the right
        # moment to record the peak.
        self.allocations += self.allocations_since
        self.peak_live = max(self.peak_live, len(self.objects))
        gray: list = []

        def mark(value) -> None:
            if type(value) in _HEAP_TYPES and not value.marked:
                if value.freed:
                    raise GCError("marking an object that was already freed")
                value.marked = True
                gray.append(value)

        vm.mark_roots(mark)
        while gray:
            _trace(gray.pop(), mark)

        survivors = []
        freed = 0
        for obj in self.objects:
            if obj.marked:
                obj.marked = False
                survivors.append(obj)
            else:
                _release(obj)
                freed += 1
        self.objects = survivors

        self.freed += freed
        self.collections += 1
        self.allocations_since = 0
        # Collect again when the heap has doubled. Scaling the threshold with the
        # live set keeps total collection work proportional to allocation, so a
        # program holding a large live set is not collected on every handful of
        # new objects.
        self.threshold = max(MIN_THRESHOLD, len(survivors) * 2)

        pause = time.perf_counter() - started
        self.pause_total_s += pause
        self.pause_max_s = max(self.pause_max_s, pause)
        return freed

    @property
    def live(self) -> int:
        return len(self.objects)

    @property
    def total_allocations(self) -> int:
        return self.allocations + self.allocations_since

    def stats(self) -> dict[str, object]:
        return {
            "allocations": self.allocations + self.allocations_since,
            "collections": self.collections,
            "freed": self.freed,
            "live": self.live,
            "peak_live": max(self.peak_live, len(self.objects)),
            "pause_total_ms": round(self.pause_total_s * 1000, 3),
            "pause_max_ms": round(self.pause_max_s * 1000, 3),
            "stress": self.stress,
        }


class ObjClosure:
    __slots__ = ("function", "upvalues", "marked", "freed", "__weakref__")
    name = property(lambda self: self.function.name)

    def __init__(self, function):
        self.function = function
        self.upvalues: list = []
        self.marked = False
        self.freed = False


class ObjUpvalue:
    """A captured variable. Open while its slot is still on the stack, then
    closed: the value is copied in and `slot` becomes -1."""

    __slots__ = ("slot", "value", "marked", "freed", "__weakref__")

    def __init__(self, slot: int):
        self.slot = slot
        self.value = None
        self.marked = False
        self.freed = False


_HEAP_TYPES = (KList, ObjClosure, ObjUpvalue)


def _trace(obj, mark) -> None:
    kind = type(obj)
    if kind is KList:
        for item in obj.items:
            mark(item)
    elif kind is ObjClosure:
        for upvalue in obj.upvalues:
            mark(upvalue)
    elif kind is ObjUpvalue:
        if obj.slot < 0:
            mark(obj.value)   # an open upvalue's value is on the stack, a root already


def _release(obj) -> None:
    obj.freed = True
    kind = type(obj)
    if kind is KList:
        obj.items = []
    elif kind is ObjClosure:
        obj.upvalues = []
    else:
        obj.value = None
