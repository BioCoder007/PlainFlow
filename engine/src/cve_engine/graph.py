"""Resolve imports and calls across files, by reading only.

A call is linked only in the four cases below. Anything else stays
unresolved (target None); nothing is guessed.
"""
from __future__ import annotations

import posixpath

from .models import FileEdge, FileNode, FunctionNode


def resolve(files: list[FileNode]) -> list[FileEdge]:
    by_path = {f.path: f for f in files}
    roots = [""] + (["src/"] if any(p.startswith("src/") for p in by_path) else [])
    top_level = {
        f.path: {fn.qualname: fn.id for fn in f.functions
                 if "." not in fn.qualname and fn.qualname != "<module>"}
        for f in files
    }
    edges: set[tuple[str, str, str]] = set()

    def module_file(module: str, importer: str) -> str | None:
        if module.startswith("."):
            level = len(module) - len(module.lstrip("."))
            base = posixpath.dirname(importer)
            for _ in range(level - 1):
                if not base:
                    return None  # the import climbs above the repo root
                base = posixpath.dirname(base)
            rest = module.lstrip(".").replace(".", "/")
            candidates = [posixpath.join(base, rest) if rest else base]
        else:
            candidates = [root + module.replace(".", "/") for root in roots]
        for cand in candidates:
            cand = cand.lstrip("/")
            for path in (f"{cand}.py", f"{cand}/__init__.py"):
                if path in by_path:
                    return path
        return None

    for f in files:
        func_bind: dict[str, str] = {}   # local name -> function id
        mod_bind: dict[str, str] = {}    # local dotted name -> file path
        bound_by: dict[str, tuple[str, str]] = {}  # local name -> (module, imported)
        ambiguous: set[str] = set()
        for imp in f.imports:
            imp.target = module_file(imp.module, f.path)
            if imp.target and imp.target != f.path:
                edges.add((f.path, imp.target, "import"))
            for local, imported in imp.names.items():
                # A name imported from two places (try/except fallbacks) is ambiguous.
                if bound_by.setdefault(local, (imp.module, imported)) != (imp.module, imported):
                    ambiguous.add(local)
                if imported == "":
                    if imp.target:
                        mod_bind[local] = imp.target
                    continue
                if imp.target and imported in top_level[imp.target]:
                    func_bind[local] = top_level[imp.target][imported]
                    continue
                sub = module_file(f"{imp.module}.{imported}", f.path)
                if sub:
                    mod_bind[local] = sub

        for local in ambiguous:
            func_bind.pop(local, None)
            mod_bind.pop(local, None)

        own_ids = {fn.id for fn in f.functions}
        for fn in f.functions:
            for call in fn.calls:
                call.target = _resolve_call(
                    call, fn, f.path, own_ids, top_level, func_bind, mod_bind)
                if call.target:
                    target_file = call.target.split("::", 1)[0]
                    if target_file != f.path:
                        edges.add((f.path, target_file, "call"))

    return [FileEdge(s, t, k) for s, t, k in sorted(edges)]


def _resolve_call(call, caller: FunctionNode, path: str, own_ids: set[str],
                  top_level: dict[str, dict[str, str]],
                  func_bind: dict[str, str], mod_bind: dict[str, str]) -> str | None:
    name = call.name
    if name == "<dynamic>":
        return None
    parts = name.split(".")
    if call.local and parts[0] != "self":
        return None  # the name is bound inside the caller: not ours to guess
    if len(parts) == 1:
        # 1. top-level function in the same file; 2. function imported by name
        return top_level[path].get(name) or func_bind.get(name)
    if parts[0] == "self":
        # 4. self.method() where the same class defines method
        if len(parts) != 2 or "." not in caller.qualname:
            return None
        owner = caller.qualname.rsplit(".", 1)[0]
        if owner.endswith("<locals>"):
            return None
        candidate = f"{path}::{owner}.{parts[1]}"
        return candidate if candidate in own_ids else None
    # 3. module_alias.function()
    target_file = mod_bind.get(".".join(parts[:-1]))
    if target_file:
        return top_level[target_file].get(parts[-1])
    return None
