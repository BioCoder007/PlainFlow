from cve_engine.parser import parse_file

SRC = '''import os
from pkg.util import helper

class Repo:
    def save(self, x):
        return helper(x)

def outer():
    def inner():
        pass
    inner()
    handlers[0]()
'''


def test_functions_and_qualnames():
    node = parse_file("m.py", SRC)
    assert [f.qualname for f in node.functions] == [
        "Repo.save", "outer", "outer.<locals>.inner"]
    assert node.functions[0].id == "m.py::Repo.save"
    assert node.functions[0].name == "save"
    assert (node.functions[0].line_start, node.functions[0].line_end) == (5, 6)


def test_imports():
    node = parse_file("m.py", SRC)
    assert [(i.module, i.line) for i in node.imports] == [("os", 1), ("pkg.util", 2)]


def test_relative_imports_keep_leading_dots():
    node = parse_file("pkg/m.py", "from . import x\nfrom .sib import y\nfrom .. import z\n")
    assert [i.module for i in node.imports] == [".x", ".sib", "..z"]


def test_calls_exclude_nested_defs_and_mark_dynamic():
    outer = parse_file("m.py", SRC).functions[1]
    assert [c.name for c in outer.calls] == ["inner", "<dynamic>"]
    assert [c.line for c in outer.calls] == [11, 12]


def test_attribute_call_names_are_dotted():
    save = parse_file("m.py", "class A:\n    def f(self):\n        self.g()\n        a.b.c()\n").functions[0]
    assert [c.name for c in save.calls] == ["self.g", "a.b.c"]


def test_script_gets_module_function():
    node = parse_file("s.py", "import sys\nx = 1\nprint(x)\n")
    assert node.functions[0].qualname == "<module>"
    assert node.functions[0].id == "s.py::<module>"
    assert (node.functions[0].line_start, node.functions[0].line_end) == (1, 3)
    assert [c.name for c in node.functions[0].calls] == ["print"]


def test_file_with_only_defs_has_no_module_function():
    assert all(f.qualname != "<module>" for f in parse_file("m.py", SRC).functions)


def test_docstring_only_module_has_no_module_function():
    assert parse_file("d.py", '"""Doc."""\nimport os\n').functions == []


def test_async_function_is_parsed():
    node = parse_file("a.py", "async def go():\n    await x()\n")
    assert [f.qualname for f in node.functions] == ["go"]


def test_syntax_error_sets_parse_error():
    node = parse_file("bad.py", "def f(:\n    pass\n")
    assert node.functions == [] and node.parse_error.startswith("line 1:")
    assert node.line_count == 2


def test_empty_file():
    node = parse_file("e.py", "")
    assert node.functions == [] and node.parse_error is None and node.line_count == 0


# -- final review C3, I1 ------------------------------------------------------

def test_redefined_functions_get_unique_ids():
    src = ("class C:\n    @property\n    def x(self):\n        return 1\n"
           "    @x.setter\n    def x(self, v):\n        self._x = v\n")
    fns = parse_file("c.py", src).functions
    assert [f.qualname for f in fns] == ["C.x", "C.x"]
    assert [f.id for f in fns] == ["c.py::C.x", "c.py::C.x@6"]


def test_form_feed_does_not_shift_step_labels():
    node = parse_file("f.py", "import os\n\x0c\ndef f():\n    a = 1\n    return a\n")
    f = next(fn for fn in node.functions if fn.name == "f")
    assert [(s.line_start, s.label) for s in f.steps] == [(4, "a = 1"), (5, "return a")]
    assert node.line_count == 5


def test_module_flow_leaves_out_functions_and_classes_and_labels_docstring():
    from cve_engine.parser import parse_file
    src = '"""\nTool docs.\n"""\nimport os\nX = 1\n\nclass A:\n    def f(self):\n        return 1\n\nY = 2\nif X:\n    Y = 3\n'
    node = parse_file("m.py", src)
    mod = next(f for f in node.functions if f.qualname == "<module>")
    assert [(s.kind, s.line_start, s.line_end) for s in mod.steps] == [
        ("block", 1, 5), ("block", 11, 11), ("branch", 12, 12), ("block", 13, 13)]
    assert mod.steps[0].label == '""" Tool docs.'
    assert ("s1", "s2") in [(e.source, e.target) for e in mod.edges]
