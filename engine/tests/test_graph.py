from pathlib import Path

from cve_engine.build import build_repo_model

FIXTURES = Path(__file__).parent / "fixtures"


def file(model, path):
    return next(f for f in model.files if f.path == path)


def call(file_node, name):
    return next(c for fn in file_node.functions for c in fn.calls if c.name == name)


def write(root, rel, text=""):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_import_and_cross_file_call_resolve():
    model = build_repo_model(FIXTURES / "mini_repo")
    app = file(model, "app.py")
    assert [(i.module, i.target) for i in app.imports] == [
        ("json", None), ("pkg.util", "pkg/util.py")]
    assert call(app, "util.clean").target == "pkg/util.py::clean"
    assert call(app, "json.dumps").target is None


def test_same_file_call_resolves_and_dynamic_call_does_not():
    util = file(build_repo_model(FIXTURES / "mini_repo"), "pkg/util.py")
    assert call(util, "_strip").target == "pkg/util.py::_strip"
    assert call(util, "<dynamic>").target is None
    assert call(util, "getattr").target is None


def test_file_edges_deduplicated():
    model = build_repo_model(FIXTURES / "mini_repo")
    assert [(e.source, e.target, e.kind) for e in model.file_edges] == [
        ("app.py", "pkg/util.py", "call"), ("app.py", "pkg/util.py", "import")]


def test_self_method_call_resolves(tmp_path):
    write(tmp_path, "a.py", "class A:\n    def run(self):\n        self.step()\n        self.missing()\n    def step(self):\n        pass\n")
    a = file(build_repo_model(tmp_path), "a.py")
    assert call(a, "self.step").target == "a.py::A.step"
    assert call(a, "self.missing").target is None


def test_from_import_function_resolves(tmp_path):
    write(tmp_path, "lib.py", "def helper():\n    pass\n")
    write(tmp_path, "main.py", "from lib import helper as h\n\ndef go():\n    h()\n")
    main = file(build_repo_model(tmp_path), "main.py")
    assert call(main, "h").target == "lib.py::helper"


def test_from_package_import_module_resolves(tmp_path):
    write(tmp_path, "pkg/__init__.py")
    write(tmp_path, "pkg/mod.py", "def foo():\n    pass\n")
    write(tmp_path, "main.py", "from pkg import mod\n\ndef go():\n    mod.foo()\n")
    main = file(build_repo_model(tmp_path), "main.py")
    assert call(main, "mod.foo").target == "pkg/mod.py::foo"


def test_relative_import_resolves(tmp_path):
    write(tmp_path, "pkg/__init__.py")
    write(tmp_path, "pkg/sib.py", "def y():\n    pass\n")
    write(tmp_path, "pkg/m.py", "from .sib import y\n\ndef go():\n    y()\n")
    m = file(build_repo_model(tmp_path), "pkg/m.py")
    assert m.imports[0].target == "pkg/sib.py"
    assert call(m, "y").target == "pkg/sib.py::y"


def test_src_layout_resolves(tmp_path):
    write(tmp_path, "src/pkg/__init__.py")
    write(tmp_path, "src/pkg/a.py", "def f():\n    pass\n")
    write(tmp_path, "scripts/run.py", "import pkg.a\n\npkg.a.f()\n")
    run = file(build_repo_model(tmp_path), "scripts/run.py")
    assert run.imports[0].target == "src/pkg/a.py"
    assert call(run, "pkg.a.f").target == "src/pkg/a.py::f"


def test_call_to_unknown_name_is_unresolved(tmp_path):
    write(tmp_path, "a.py", "def go(x):\n    x.save()\n    nothing()\n")
    a = file(build_repo_model(tmp_path), "a.py")
    assert call(a, "x.save").target is None and call(a, "nothing").target is None


def test_parent_relative_import_of_submodule_resolves(tmp_path):
    write(tmp_path, "top/__init__.py")
    write(tmp_path, "top/lib/__init__.py")
    write(tmp_path, "top/lib/mod.py", "def foo():\n    pass\n")
    write(tmp_path, "top/app/__init__.py")
    write(tmp_path, "top/app/m.py", "from ..lib import mod\n\ndef go():\n    mod.foo()\n")
    m = file(build_repo_model(tmp_path), "top/app/m.py")
    assert call(m, "mod.foo").target == "top/lib/mod.py::foo"


# -- final review C1: a name bound in the caller is never linked ------------

def test_parameter_shadowing_a_function_is_unresolved(tmp_path):
    write(tmp_path, "a.py", "def helper():\n    pass\n\ndef apply(helper, x):\n    return helper(x)\n")
    assert call(file(build_repo_model(tmp_path), "a.py"), "helper").target is None


def test_local_assignment_shadowing_a_function_is_unresolved(tmp_path):
    write(tmp_path, "a.py", "def save():\n    pass\n\ndef go(obj):\n    save = obj.save\n    save()\n")
    assert call(file(build_repo_model(tmp_path), "a.py"), "save").target is None


def test_nested_def_shadowing_a_function_is_unresolved(tmp_path):
    write(tmp_path, "a.py", "def save():\n    pass\n\ndef g():\n    def save():\n        pass\n    save()\n")
    assert call(file(build_repo_model(tmp_path), "a.py"), "save").target is None


def test_enclosing_function_parameter_shadows_in_a_closure(tmp_path):
    write(tmp_path, "a.py", "def helper():\n    pass\n\ndef outer(helper):\n    def inner():\n        helper()\n    return inner\n")
    assert call(file(build_repo_model(tmp_path), "a.py"), "helper").target is None


def test_parameter_shadowing_an_imported_module_is_unresolved(tmp_path):
    write(tmp_path, "db.py", "def connect():\n    pass\n")
    write(tmp_path, "a.py", "import db\n\ndef go(db):\n    db.connect()\n")
    model = build_repo_model(tmp_path)
    assert call(file(model, "a.py"), "db.connect").target is None
    assert ("a.py", "db.py", "call") not in {(e.source, e.target, e.kind) for e in model.file_edges}


def test_module_level_reassignment_shadows_an_import(tmp_path):
    write(tmp_path, "db.py", "def connect():\n    pass\n")
    write(tmp_path, "a.py", "import db\ndb = make()\n\ndef go():\n    db.connect()\n")
    assert call(file(build_repo_model(tmp_path), "a.py"), "db.connect").target is None


def test_function_level_imports_do_not_bind_file_wide(tmp_path):
    write(tmp_path, "x.py", "def run():\n    pass\n")
    write(tmp_path, "y.py", "def run():\n    pass\n")
    write(tmp_path, "a.py", "def f():\n    from x import run\n    run()\n\ndef g():\n    from y import run\n    run()\n")
    a = file(build_repo_model(tmp_path), "a.py")
    assert [c.target for fn in a.functions for c in fn.calls] == [None, None]
    assert [i.target for i in a.imports] == ["x.py", "y.py"]


def test_name_imported_from_two_modules_is_unresolved(tmp_path):
    write(tmp_path, "fast.py", "def loads():\n    pass\n")
    write(tmp_path, "slow.py", "def loads():\n    pass\n")
    write(tmp_path, "a.py", "try:\n    from fast import loads\nexcept ImportError:\n    from slow import loads\n\ndef go():\n    loads()\n")
    assert call(file(build_repo_model(tmp_path), "a.py"), "loads").target is None


def test_relative_import_above_the_repo_root_is_unresolved(tmp_path):
    write(tmp_path, "x.py", "def f():\n    pass\n")
    write(tmp_path, "a.py", "from ... import x\n")
    assert file(build_repo_model(tmp_path), "a.py").imports[0].target is None


def test_self_method_still_resolves_with_self_as_a_parameter(tmp_path):
    write(tmp_path, "a.py", "class A:\n    def run(self):\n        self.step()\n    def step(self):\n        pass\n")
    assert call(file(build_repo_model(tmp_path), "a.py"), "self.step").target == "a.py::A.step"
