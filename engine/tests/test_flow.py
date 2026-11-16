import ast

from cve_engine.flow import build_flow


def flow(src):
    tree = ast.parse(src)
    return build_flow(tree.body[0].body, src.splitlines())


def E(edges):
    return {(e.source, e.target, e.label) for e in edges}


def test_straight_run_is_one_block():
    steps, edges = flow("def f():\n    a = 1\n    b = 2\n    c = a + b\n")
    assert [(s.kind, s.line_start, s.line_end) for s in steps] == [("block", 2, 4)]
    assert edges == []


def test_if_else_then_return():
    src = "def f(x):\n    if x > 0:\n        y = 1\n    else:\n        y = 2\n    return y\n"
    steps, edges = flow(src)
    assert [(s.id, s.kind, s.line_start) for s in steps] == [
        ("s1", "branch", 2), ("s2", "block", 3), ("s3", "block", 5), ("s4", "return", 6)]
    assert E(edges) == {("s1", "s2", "true"), ("s1", "s3", "false"),
                        ("s2", "s4", None), ("s3", "s4", None)}


def test_branch_step_covers_only_the_test_line():
    steps, _ = flow("def f(x):\n    if x > 0:\n        y = 1\n        z = 2\n")
    assert (steps[0].line_start, steps[0].line_end) == (2, 2)
    assert steps[0].label == "if x > 0:"


def test_if_without_else_false_edge_skips_body():
    steps, edges = flow("def f(x):\n    if x:\n        x = 0\n    return x\n")
    assert ("s1", "s3", "false") in E(edges)


def test_if_without_else_at_end_has_no_false_edge():
    steps, edges = flow("def f(x):\n    if x:\n        x = 0\n")
    assert E(edges) == {("s1", "s2", "true")}


def test_elif_is_its_own_branch():
    src = "def f(x):\n    if x == 1:\n        a()\n    elif x == 2:\n        b()\n    else:\n        c()\n"
    steps, edges = flow(src)
    assert [s.kind for s in steps] == ["branch", "block", "branch", "block", "block"]
    assert E(edges) == {("s1", "s2", "true"), ("s1", "s3", "false"),
                        ("s3", "s4", "true"), ("s3", "s5", "false")}


def test_for_loop_edges():
    src = "def f(xs):\n    t = 0\n    for x in xs:\n        t += x\n    return t\n"
    steps, edges = flow(src)
    assert [s.kind for s in steps] == ["block", "loop", "block", "return"]
    assert E(edges) == {("s1", "s2", None), ("s2", "s3", "loop"),
                        ("s3", "s2", None), ("s2", "s4", "exit")}


def test_while_loop_at_end_has_no_exit_edge():
    steps, edges = flow("def f(n):\n    while n:\n        n -= 1\n")
    assert E(edges) == {("s1", "s2", "loop"), ("s2", "s1", None)}


def test_break_goes_to_step_after_loop_and_continue_to_loop():
    src = ("def f(xs):\n    for x in xs:\n        if x < 0:\n            break\n"
           "        if x == 0:\n            continue\n        use(x)\n    done()\n")
    steps, edges = flow(src)
    assert [s.kind for s in steps] == [
        "loop", "branch", "block", "branch", "block", "block", "block"]
    assert ("s3", "s7", None) in E(edges) and ("s5", "s1", None) in E(edges)
    assert ("s3", "s4", None) not in E(edges)


def test_try_except_finally():
    src = ("def f():\n    try:\n        a()\n    except ValueError:\n        b()\n"
           "    finally:\n        c()\n")
    steps, edges = flow(src)
    assert [s.kind for s in steps] == ["try", "block", "block", "block"]
    assert E(edges) == {("s1", "s2", None), ("s1", "s3", "except"),
                        ("s2", "s4", None), ("s3", "s4", None)}


def test_with_step_then_body():
    steps, edges = flow("def f(p):\n    with open(p) as fh:\n        data = fh.read()\n    return data\n")
    assert [s.kind for s in steps] == ["with", "block", "return"]
    assert E(edges) == {("s1", "s2", None), ("s2", "s3", None)}


def test_match_has_one_edge_per_case_labelled_with_pattern():
    src = "def f(c):\n    match c:\n        case 1:\n            a()\n        case _:\n            b()\n"
    steps, edges = flow(src)
    assert [s.kind for s in steps] == ["branch", "block", "block"]
    assert E(edges) == {("s1", "s2", "1"), ("s1", "s3", "_")}


def test_return_inside_branch_has_no_outgoing_edge():
    steps, edges = flow("def f(x):\n    if x:\n        return 1\n    return 2\n")
    assert steps[1].kind == "return"
    assert not any(e.source == "s2" for e in edges)


def test_raise_is_its_own_step_and_ends_the_block():
    steps, edges = flow("def f(x):\n    check(x)\n    raise ValueError(x)\n")
    assert [s.kind for s in steps] == ["block", "raise"]
    assert E(edges) == {("s1", "s2", None)}


def test_nested_def_counts_as_a_simple_statement():
    steps, _ = flow("def f():\n    a = 1\n    def g():\n        return 2\n    return g\n")
    assert [(s.kind, s.line_start, s.line_end) for s in steps] == [
        ("block", 2, 4), ("return", 5, 5)]


def test_label_is_first_line_truncated_to_80():
    steps, _ = flow("def f():\n    value = " + "1 + " * 40 + "1\n")
    assert len(steps[0].label) == 80


def test_empty_body_pass_only():
    steps, edges = flow("def f():\n    pass\n")
    assert len(steps) == 1 and edges == []


# -- final review C2, I4 ------------------------------------------------------

def test_return_inside_try_runs_through_finally():
    steps, edges = flow("def f():\n    try:\n        return compute()\n    finally:\n        cleanup()\n")
    assert [s.kind for s in steps] == ["try", "return", "block"]
    assert E(edges) == {("s1", "s2", None), ("s2", "s3", None)}


def test_raise_in_handler_runs_through_finally():
    src = ("def f():\n    try:\n        a()\n    except E:\n        raise\n"
           "    finally:\n        c()\n    d()\n")
    steps, edges = flow(src)
    assert [s.kind for s in steps] == ["try", "block", "raise", "block", "block"]
    assert ("s3", "s4", None) in E(edges)


def test_break_inside_try_finally_goes_through_finally():
    src = ("def f(xs):\n    for x in xs:\n        try:\n            if x:\n                break\n"
           "            work()\n        finally:\n            cleanup()\n    done()\n")
    steps, edges = flow(src)
    # s1 loop, s2 try, s3 branch, s4 block(break), s5 block(work), s6 block(cleanup), s7 block(done)
    assert [s.kind for s in steps] == ["loop", "try", "branch", "block", "block", "block", "block"]
    assert ("s4", "s6", None) in E(edges)
    assert ("s6", "s7", "break") in E(edges)
    assert ("s4", "s7", None) not in E(edges)
    assert ("s6", "s1", None) in E(edges)  # the normal path loops again


def test_continue_inside_try_finally_goes_through_finally():
    src = ("def f(xs):\n    for x in xs:\n        try:\n            if x:\n                continue\n"
           "            work()\n        finally:\n            cleanup()\n")
    steps, edges = flow(src)
    assert ("s4", "s6", None) in E(edges)
    assert ("s4", "s1", None) not in E(edges)


def test_break_in_a_loop_nested_inside_try_is_not_routed_through_finally():
    src = ("def f(xs):\n    try:\n        for x in xs:\n            break\n"
           "    finally:\n        cleanup()\n")
    steps, edges = flow(src)
    # s1 try, s2 loop, s3 block(break), s4 block(cleanup)
    assert E(edges) == {("s1", "s2", None), ("s2", "s3", "loop"),
                        ("s2", "s4", "exit"), ("s3", "s4", None)}


def test_while_true_has_no_exit_edge():
    src = "def f():\n    while True:\n        x = get()\n        if x:\n            return x\n    unreachable()\n"
    steps, edges = flow(src)
    assert not any(e.label == "exit" for e in edges)
    assert not any(e.target == "s5" for e in edges)


def test_while_true_with_break_exits_through_the_break():
    steps, edges = flow("def f():\n    while 1:\n        if done():\n            break\n    after()\n")
    assert ("s3", "s4", None) in E(edges)
    assert not any(e.label == "exit" for e in edges)
