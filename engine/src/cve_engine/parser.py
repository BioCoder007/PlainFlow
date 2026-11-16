"""One file's text -> FileNode. The text is parsed with ast, never executed."""
from __future__ import annotations

import ast

from . import flow
from .models import CallRef, FileNode, FunctionNode, ImportRef

_SCOPE = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
_NAMED_SCOPE = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def split_lines(text: str) -> list[str]:
    """Lines as Python's parser counts them: split on newline only."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def parse_file(path: str, text: str) -> FileNode:
    lines = split_lines(text)
    node = FileNode(path=path, line_count=len(lines))
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        node.parse_error = f"line {e.lineno}: {e.msg}"
        return node
    except (ValueError, RecursionError) as e:  # null bytes, pathological nesting
        node.parse_error = f"line 1: {e}"
        return node

    node.imports = _imports(tree)
    module_bound = _bound_names(tree.body, local_scope=False)
    if _has_module_code(tree):
        steps, edges = flow.build_flow(tree.body, lines, skip=_NAMED_SCOPE)
        node.functions.append(FunctionNode(
            id=f"{path}::<module>", name="<module>", qualname="<module>",
            line_start=1, line_end=len(lines),
            steps=steps, edges=edges, calls=_calls(tree.body, module_bound)))
    used = {fn.id for fn in node.functions}
    _collect_functions(tree.body, [], path, lines, node.functions, module_bound, used)
    return node


def _has_module_code(tree: ast.Module) -> bool:
    for i, stmt in enumerate(tree.body):
        if isinstance(stmt, (ast.Import, ast.ImportFrom, *_NAMED_SCOPE)):
            continue
        if (i == 0 and isinstance(stmt, ast.Expr)
                and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, str)):
            continue
        return True
    return False


def _collect_functions(body, stack, path, lines, out, bound, used) -> None:
    """Depth-first, in source order. `bound` holds names bound in enclosing scopes."""
    for stmt in _scopes_in(body):
        if isinstance(stmt, ast.ClassDef):
            _collect_functions(stmt.body, stack + [stmt.name], path, lines, out, bound, used)
            continue
        qualname = ".".join(stack + [stmt.name])
        fn_id = f"{path}::{qualname}"
        if fn_id in used:  # redefinition: property setter, overload, if/else def
            fn_id = f"{fn_id}@{stmt.lineno}"
        used.add(fn_id)
        own = bound | _argument_names(stmt.args) | _bound_names(stmt.body, local_scope=True)
        steps, edges = flow.build_flow(stmt.body, lines)
        out.append(FunctionNode(
            id=fn_id, name=stmt.name, qualname=qualname,
            line_start=stmt.lineno, line_end=stmt.end_lineno or stmt.lineno,
            steps=steps, edges=edges, calls=_calls(stmt.body, own)))
        _collect_functions(
            stmt.body, stack + [stmt.name, "<locals>"], path, lines, out, own, used)


def _scopes_in(body) -> list[ast.AST]:
    """def/class statements at this scope level, including ones nested in if/for/try."""
    found: list[ast.AST] = []
    todo = list(body)
    while todo:
        n = todo.pop(0)
        if isinstance(n, _NAMED_SCOPE):
            found.append(n)
            continue
        if isinstance(n, ast.Lambda):
            continue
        todo.extend(ast.iter_child_nodes(n))
    found.sort(key=lambda n: (n.lineno, n.col_offset))
    return found


def _argument_names(args: ast.arguments) -> set[str]:
    names = {a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)}
    for extra in (args.vararg, args.kwarg):
        if extra is not None:
            names.add(extra.arg)
    return names


def _bound_names(body, local_scope: bool) -> set[str]:
    """Names this scope rebinds: assignments, loop and with targets and
    except-as names. Inside a function (local_scope) nested def/class names and
    local imports count too; at module level those are the file's own
    definitions and imports, which graph.py resolves."""
    names: set[str] = set()
    todo = list(body)
    while todo:
        n = todo.pop()
        if isinstance(n, _NAMED_SCOPE):
            if local_scope:
                names.add(n.name)
            continue
        if isinstance(n, ast.Lambda):
            continue
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            names.add(n.id)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            names.add(n.name)
        elif local_scope and isinstance(n, (ast.Import, ast.ImportFrom)):
            for alias in n.names:
                names.add((alias.asname or alias.name).split(".")[0])
        todo.extend(ast.iter_child_nodes(n))
    return names


def _calls(body, bound: set[str]) -> list[CallRef]:
    """Calls made directly in this body, not inside nested defs or classes."""
    calls: list[ast.Call] = []
    todo = list(body)
    while todo:
        n = todo.pop()
        if isinstance(n, _NAMED_SCOPE):
            continue
        if isinstance(n, ast.Call):
            calls.append(n)
        todo.extend(ast.iter_child_nodes(n))
    calls.sort(key=lambda c: (c.lineno, c.col_offset))
    refs = []
    for c in calls:
        name = _callee_name(c.func)
        refs.append(CallRef(name=name, line=c.lineno, local=name.split(".")[0] in bound))
    return refs


def _callee_name(func: ast.expr) -> str:
    parts: list[str] = []
    while isinstance(func, ast.Attribute):
        parts.append(func.attr)
        func = func.value
    if isinstance(func, ast.Name):
        parts.append(func.id)
        return ".".join(reversed(parts))
    return "<dynamic>"


def _imports(tree: ast.Module) -> list[ImportRef]:
    """Every import in the file. Only module-level imports carry `names`
    (what they bind file-wide); an import inside a def or class binds locally."""
    refs: list[tuple[int, int, ImportRef]] = []

    def visit(node: ast.AST, module_level: bool) -> None:
        for n in ast.iter_child_nodes(node):
            if isinstance(n, ast.Import):
                for i, alias in enumerate(n.names):
                    local = alias.asname or alias.name
                    names = {local: ""} if module_level else {}
                    refs.append((n.lineno, i, ImportRef(alias.name, n.lineno, names=names)))
            elif isinstance(n, ast.ImportFrom):
                dots = "." * n.level
                if n.module:
                    names = {(a.asname or a.name): a.name for a in n.names} if module_level else {}
                    refs.append((n.lineno, 0, ImportRef(dots + n.module, n.lineno, names=names)))
                else:  # from . import x  -> one module per name
                    for i, alias in enumerate(n.names):
                        local = alias.asname or alias.name
                        names = {local: ""} if module_level else {}
                        refs.append((n.lineno, i, ImportRef(dots + alias.name, n.lineno, names=names)))
            else:
                visit(n, module_level and not isinstance(n, _SCOPE))

    visit(tree, True)
    refs.sort(key=lambda r: (r[0], r[1]))
    return [r[2] for r in refs]
