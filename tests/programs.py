"""The conformance programs.

Each one runs through the tree-walker, the bytecode VM, and the VM with the
collector in stress mode, and all three must print exactly the expected lines.
That is what makes the benchmark a comparison of two implementations of one
language rather than of two languages that happen to look alike.
"""

PROGRAMS: dict[str, tuple[str, list[str]]] = {

    "arithmetic and precedence": ("""
        print(1 + 2 * 3);
        print((1 + 2) * 3);
        print(10 - 4 - 3);
        print(7 % 3);
        print(-2 * -3);
        print(7 / 2);
        print(8 / 4);
        print(2.5 * 2);
    """, ["7", "9", "3", "1", "6", "3.5", "2", "5.0"]),

    "comparison and equality": ("""
        print(1 < 2); print(2 <= 2); print(3 > 4); print(4 >= 5);
        print(1 == 1.0); print(1 != 2); print("a" == "a");
        print(nil == false); print(true == 1); print("b" > "a");
    """, ["true", "true", "false", "false", "true", "true", "true",
          "false", "false", "true"]),

    "truthiness": ("""
        if (0) print("zero is truthy");
        if ("") print("empty string is truthy");
        if (nil) print("never"); else print("nil is falsy");
        print(!nil); print(!0);
    """, ["zero is truthy", "empty string is truthy", "nil is falsy", "true", "false"]),

    "short circuit returns the deciding value": ("""
        print(nil or "default");
        print("first" or "second");
        print(false and undefined_function());
        print(1 and 2);
        let calls = 0;
        fn bump() { calls = calls + 1; return true; }
        true or bump(); false and bump();
        print(calls);
    """, ["default", "first", "false", "2", "0"]),

    "strings": ("""
        let s = "hello" + ", " + "world";
        print(s); print(len(s));
        print("tab\\tand\\nnewline");
        print(str(42) + "!");
    """, ["hello, world", "12", "tab\tand\nnewline", "42!"]),

    "global variables": ("""
        let a = 1;
        let b;
        print(b);
        a = a + 10;
        print(a);
        let a = "redeclared at global scope is allowed";
        print(a);
    """, ["nil", "11", "redeclared at global scope is allowed"]),

    "block scope and shadowing": ("""
        let x = "global";
        {
            let x = "outer block";
            {
                let x = "inner block";
                print(x);
            }
            print(x);
        }
        print(x);
    """, ["inner block", "outer block", "global"]),

    "initialiser reads the enclosing variable": ("""
        let x = 1;
        { let x = x + 1; print(x); }
        print(x);
    """, ["2", "1"]),

    "while loop": ("""
        let i = 0;
        let total = 0;
        while (i < 100) { total = total + i; i = i + 1; }
        print(total);
    """, ["4950"]),

    "for loop with its own scope": ("""
        let total = 0;
        for (let i = 1; i <= 10; i = i + 1) total = total + i * i;
        print(total);
        let i = "outer i untouched";
        for (let i = 0; i < 3; i = i + 1) {}
        print(i);
    """, ["385", "outer i untouched"]),

    "recursion": ("""
        fn fib(n) { if (n < 2) return n; return fib(n - 1) + fib(n - 2); }
        print(fib(20));
        fn fact(n) { if (n <= 1) return 1; return n * fact(n - 1); }
        print(fact(20));
    """, ["6765", "2432902008176640000"]),

    "functions are values": ("""
        fn twice(f, x) { return f(f(x)); }
        fn inc(n) { return n + 1; }
        print(twice(inc, 5));
        print(twice(fn(n) { return n * 10; }, 3));
        print(inc);
    """, ["7", "300", "<fn inc>"]),

    "implicit nil return": ("""
        fn nothing() { let x = 1; }
        print(nothing());
        fn early(n) { if (n > 0) return "positive"; }
        print(early(1)); print(early(-1));
    """, ["nil", "positive", "nil"]),

    "closure counter": ("""
        fn counter() {
            let n = 0;
            return fn() { n = n + 1; return n; };
        }
        let a = counter();
        let b = counter();
        a(); a();
        print(a()); print(b());
    """, ["3", "1"]),

    "closures share a captured variable": ("""
        fn pair() {
            let value = 0;
            let set = fn(v) { value = v; };
            let get = fn() { return value; };
            return [set, get];
        }
        let p = pair();
        p[0](42);
        print(p[1]());
    """, ["42"]),

    "a captured variable outlives its function": ("""
        fn make() {
            let message = "still here";
            fn inner() { return message; }
            return inner;
        }
        let f = make();
        let noise = [1, 2, 3, 4, 5, 6, 7, 8];
        print(f());
    """, ["still here"]),

    "closures capture through several levels": ("""
        fn outer() {
            let x = "from outer";
            fn middle() {
                fn inner() { return x; }
                return inner;
            }
            return middle();
        }
        print(outer()());
    """, ["from outer"]),

    "each loop iteration closes over its own variable": ("""
        let fns = [];
        for (let i = 0; i < 3; i = i + 1) {
            let j = i;
            push(fns, fn() { return j; });
        }
        print(fns[0]()); print(fns[1]()); print(fns[2]());
    """, ["0", "1", "2"]),

    "a closure in a block at script level": ("""
        let saved;
        {
            let hidden = "block local";
            saved = fn() { return hidden; };
        }
        print(saved());
    """, ["block local"]),

    "local recursive function": ("""
        fn run() {
            fn countdown(n) { if (n == 0) return "liftoff"; return countdown(n - 1); }
            return countdown(5);
        }
        print(run());
    """, ["liftoff"]),

    "lists": ("""
        let xs = [1, "two", nil, [3, 4]];
        print(xs); print(len(xs));
        xs[0] = 100;
        print(xs[0]); print(xs[3][1]); print(xs[-1]);
        push(xs, true);
        print(pop(xs)); print(len(xs));
        let empty = [];
        print(empty);
    """, ['[1, "two", nil, [3, 4]]', "4", "100", "4", "[3, 4]", "true", "4", "[]"]),

    "lists are shared, not copied": ("""
        let a = [1, 2];
        let b = a;
        push(b, 3);
        print(a); print(a == b); print([1] == [1]);
    """, ["[1, 2, 3]", "true", "false"]),

    "a list that contains itself prints safely": ("""
        let loop = [1];
        push(loop, loop);
        print(loop);
    """, ["[1, [...]]"]),

    "building a large list": ("""
        let squares = [];
        for (let i = 0; i < 5000; i = i + 1) push(squares, i * i);
        print(len(squares)); print(squares[4999]);
    """, ["5000", "24990001"]),

    "garbage in a loop": ("""
        let kept = [];
        for (let i = 0; i < 3000; i = i + 1) {
            let temp = [i, i + 1, [i, i]];
            if (i % 1000 == 0) push(kept, temp);
        }
        print(len(kept)); print(kept[2][2]);
    """, ["3", "[2000, 2000]"]),

    "closures as data structures": ("""
        fn cons(head, tail) { return fn(pick) { if (pick) return head; return tail; }; }
        let list = nil;
        for (let i = 0; i < 50; i = i + 1) list = cons(i, list);
        let total = 0;
        while (list != nil) { total = total + list(true); list = list(false); }
        print(total);
    """, ["1225"]),
}


#: Programs that must fail, identically, in both engines: same message, same line.
ERRORS: dict[str, tuple[str, str, int]] = {
    "undefined variable": ("print(missing);", "undefined variable 'missing'", 1),
    "assign to undefined": ("\nnever_declared = 1;", "undefined variable 'never_declared'", 2),
    "add number and string": ('let x = 1;\nprint(x + "a");', "cannot add number and string", 2),
    "subtract strings": ('print("a" - "b");', "operator - needs two numbers, got string and string", 1),
    "divide by zero": ("print(1 / 0);", "division by zero", 1),
    "compare mixed": ('print(1 < "2");', "cannot compare number with string", 1),
    "negate a string": ('print(-"x");', "cannot negate string", 1),
    "call a number": ("let n = 3;\n\nn();", "cannot call number", 3),
    "wrong arity": ("fn f(a, b) { return a; }\nf(1);", "f() takes 2 arguments, got 1", 2),
    "builtin arity": ("len();", "len() takes 1 argument, got 0", 1),
    "index out of range": ("let xs = [1];\nprint(xs[5]);", "index 5 out of range for a list of 1", 2),
    "index a string": ('print("abc"[0]);', "cannot index into string", 1),
    "non integer index": ("print([1][1.5]);", "list index must be an integer, got number", 1),
    "push onto a non list": ("push(3, 4);", "push() needs a list, got number", 1),
    "pop from empty": ("pop([]);", "pop() from an empty list", 1),
    "stack overflow": ("fn forever(n) { return forever(n + 1); }\nforever(0);",
                       "stack overflow", 1),
}
