"""Function body -> steps and step edges.

Structure comes only from the syntax tree. Each statement list is walked into
an entry step plus a set of open exits; the caller wires open exits to
whatever comes next.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field

from .models import Step, StepEdge

_LOOPS = (ast.For, ast.AsyncFor, ast.While)
_WITHS = (ast.With, ast.AsyncWith)
_TRIES = (ast.Try, ast.TryStar)
_COMPOUND = (ast.If, *_LOOPS, *_WITHS, *_TRIES, ast.Match, ast.Return, ast.Raise)
_LABEL_MAX = 80

Exit = tuple[str, str | None]  # (source step id, edge label)


@dataclass
class _Finally:
    """Early exits raised inside a try that has a finally clause."""
    loop_depth: int                                   # loops open when the try began
    abrupt: list[str] = field(default_factory=list)   # return / raise steps
    breaks: list[str] = field(default_factory=list)
    continues: list[str] = field(default_factory=list)


def build_flow(body: list[ast.stmt], source_lines: list[str],
               skip: tuple = ()) -> tuple[list[Step], list[StepEdge]]:
    """`skip` lists top-level statement types to leave out (a module's flow leaves out its
    functions and classes: each has its own flow)."""
    builder = _Builder(source_lines)
    builder.skip = skip
    builder.seq(body)
    return builder.steps, builder.edges


class _Builder:
    def __init__(self, source_lines: list[str]) -> None:
        self.lines = source_lines
        self.steps: list[Step] = []
        self.edges: list[StepEdge] = []
        self._seen: set[tuple[str, str, str | None]] = set()
        self._loops: list[tuple[str, list[Exit]]] = []  # (loop step id, break exits)
        self._finals: list[_Finally] = []
        self.skip: tuple = ()

    # -- primitives ---------------------------------------------------------
    def step(self, kind: str, start: int, end: int) -> str:
        sid = f"s{len(self.steps) + 1}"
        text = self.lines[start - 1].strip() if 0 < start <= len(self.lines) else ""
        if text.lstrip("rRbBuUfF") in ('"""', "'''"):  # a docstring that opens on its own line
            following = [t.strip() for t in self.lines[start:max(start, end)] if t.strip()]
            if following:
                text = f"{text} {following[0]}"
        self.steps.append(Step(sid, kind, text[:_LABEL_MAX], start, max(start, end)))
        return sid

    def edge(self, source: str, target: str, label: str | None = None) -> None:
        key = (source, target, label)
        if key not in self._seen:
            self._seen.add(key)
            self.edges.append(StepEdge(source, target, label))

    def connect(self, exits: list[Exit], target: str) -> None:
        for source, label in exits:
            self.edge(source, target, label)

    # -- statement lists ----------------------------------------------------
    def seq(self, stmts: list[ast.stmt]) -> tuple[str | None, list[Exit]]:
        entry: str | None = None
        open_exits: list[Exit] = []
        i = 0
        while i < len(stmts):
            stmt = stmts[i]
            if self.skip and isinstance(stmt, self.skip):
                i += 1
                continue
            if isinstance(stmt, _COMPOUND):
                unit_entry, unit_exits = self.compound(stmt)
                i += 1
            else:
                j = i
                while j < len(stmts) and not isinstance(stmts[j], (*_COMPOUND, *self.skip)):
                    j += 1
                    if isinstance(stmts[j - 1], (ast.Break, ast.Continue)):
                        break
                unit_entry, unit_exits = self.block(stmts[i:j])
                i = j
            self.connect(open_exits, unit_entry)
            if entry is None:
                entry = unit_entry
            open_exits = unit_exits
        return entry, open_exits

    def block(self, stmts: list[ast.stmt]) -> tuple[str, list[Exit]]:
        sid = self.step("block", _first_line(stmts[0]), _last_line(stmts[-1]))
        last = stmts[-1]
        if isinstance(last, (ast.Break, ast.Continue)):
            if not self._loops:
                return sid, []
            # A try/finally opened inside the current loop sits between this
            # statement and the loop: the finally clause runs first.
            final = self._finals[-1] if self._finals else None
            crosses_finally = final is not None and final.loop_depth == len(self._loops)
            if isinstance(last, ast.Break):
                if crosses_finally:
                    final.breaks.append(sid)
                else:
                    self._loops[-1][1].append((sid, None))
            elif crosses_finally:
                final.continues.append(sid)
            else:
                self.edge(sid, self._loops[-1][0])
            return sid, []
        return sid, [(sid, None)]

    # -- compound statements ------------------------------------------------
    def compound(self, stmt: ast.stmt) -> tuple[str, list[Exit]]:
        if isinstance(stmt, (ast.Return, ast.Raise)):
            kind = "return" if isinstance(stmt, ast.Return) else "raise"
            sid = self.step(kind, stmt.lineno, _last_line(stmt))
            if self._finals:
                self._finals[-1].abrupt.append(sid)  # the finally clause still runs
            return sid, []
        if isinstance(stmt, ast.If):
            return self.if_(stmt)
        if isinstance(stmt, _LOOPS):
            return self.loop(stmt)
        if isinstance(stmt, _TRIES):
            return self.try_(stmt)
        if isinstance(stmt, _WITHS):
            return self.with_(stmt)
        return self.match(stmt)

    def if_(self, stmt: ast.If) -> tuple[str, list[Exit]]:
        sid = self.step("branch", stmt.lineno, _last_line(stmt.test))
        body_entry, exits = self.seq(stmt.body)
        self.edge(sid, body_entry, "true")
        if stmt.orelse:
            else_entry, else_exits = self.seq(stmt.orelse)
            self.edge(sid, else_entry, "false")
            exits = exits + else_exits
        else:
            exits = exits + [(sid, "false")]
        return sid, exits

    def loop(self, stmt) -> tuple[str, list[Exit]]:
        header = stmt.test if isinstance(stmt, ast.While) else stmt.iter
        sid = self.step("loop", stmt.lineno, _last_line(header))
        breaks: list[Exit] = []
        self._loops.append((sid, breaks))
        body_entry, body_exits = self.seq(stmt.body)
        self._loops.pop()
        self.edge(sid, body_entry, "loop")
        self.connect(body_exits, sid)
        endless = (isinstance(stmt, ast.While) and isinstance(stmt.test, ast.Constant)
                   and bool(stmt.test.value))
        if endless:
            # `while True:` never exits through its test, only through break.
            if stmt.orelse:
                self.seq(stmt.orelse)  # unreachable, but still shown as steps
            exits: list[Exit] = []
        elif stmt.orelse:
            else_entry, exits = self.seq(stmt.orelse)
            self.edge(sid, else_entry, "exit")
        else:
            exits = [(sid, "exit")]
        return sid, exits + breaks

    def try_(self, stmt) -> tuple[str, list[Exit]]:
        sid = self.step("try", stmt.lineno, stmt.lineno)
        final = _Finally(len(self._loops)) if stmt.finalbody else None
        if final is not None:
            self._finals.append(final)
        body_entry, exits = self.seq(stmt.body)
        self.edge(sid, body_entry)
        handler_exits: list[Exit] = []
        for handler in stmt.handlers:
            h_entry, h_exits = self.seq(handler.body)
            self.edge(sid, h_entry, "except")
            handler_exits += h_exits
        if stmt.orelse:
            else_entry, else_exits = self.seq(stmt.orelse)
            self.connect(exits, else_entry)
            exits = else_exits
        exits = exits + handler_exits
        if final is not None:
            self._finals.pop()
            final_entry, final_exits = self.seq(stmt.finalbody)
            self.connect(exits, final_entry)
            for early in (*final.abrupt, *final.breaks, *final.continues):
                self.edge(early, final_entry)
            self._leave_finally(final, [source for source, _ in final_exits])
            exits = final_exits
        return sid, exits

    def _leave_finally(self, final: _Finally, ends: list[str]) -> None:
        """After the finally clause, early exits carry on to where they were headed."""
        outer = self._finals[-1] if self._finals else None
        outer_in_same_loop = outer is not None and outer.loop_depth == len(self._loops)
        if final.abrupt and outer is not None:
            outer.abrupt.extend(ends)
        if final.breaks:
            if outer_in_same_loop:
                outer.breaks.extend(ends)
            elif self._loops:
                self._loops[-1][1].extend((end, "break") for end in ends)
        if final.continues:
            if outer_in_same_loop:
                outer.continues.extend(ends)
            elif self._loops:
                for end in ends:
                    self.edge(end, self._loops[-1][0], "continue")

    def with_(self, stmt) -> tuple[str, list[Exit]]:
        end = max(_last_line(item.optional_vars or item.context_expr) for item in stmt.items)
        sid = self.step("with", stmt.lineno, end)
        body_entry, exits = self.seq(stmt.body)
        self.edge(sid, body_entry)
        return sid, exits

    def match(self, stmt: ast.Match) -> tuple[str, list[Exit]]:
        sid = self.step("branch", stmt.lineno, _last_line(stmt.subject))
        exits: list[Exit] = []
        catches_all = False
        for case in stmt.cases:
            label = ast.unparse(case.pattern)
            if case.guard is not None:
                label += f" if {ast.unparse(case.guard)}"
            case_entry, case_exits = self.seq(case.body)
            self.edge(sid, case_entry, label)
            exits += case_exits
            if (case.guard is None and isinstance(case.pattern, ast.MatchAs)
                    and case.pattern.pattern is None):
                catches_all = True
        if not catches_all:
            exits.append((sid, None))  # no case matched: falls through
        return sid, exits


def _first_line(stmt: ast.stmt) -> int:
    decorators = getattr(stmt, "decorator_list", None) or []
    return min([stmt.lineno, *(d.lineno for d in decorators)])


def _last_line(node: ast.AST) -> int:
    return getattr(node, "end_lineno", None) or node.lineno
