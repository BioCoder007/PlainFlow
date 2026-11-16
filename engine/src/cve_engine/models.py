"""The repo model: plain dataclasses that serialise to JSON."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


class _Dictable:
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Step(_Dictable):
    id: str
    kind: str  # block | branch | loop | return | raise | try | with
    label: str
    line_start: int
    line_end: int


@dataclass
class StepEdge(_Dictable):
    source: str
    target: str
    label: str | None = None


@dataclass
class CallRef(_Dictable):
    name: str
    line: int
    target: str | None = None
    # True when the first name is bound inside the caller (parameter, local
    # variable, nested def, local import). Such a call is never linked.
    local: bool = False


@dataclass
class ImportRef(_Dictable):
    module: str
    line: int
    target: str | None = None
    # local name -> imported name ("" when the local name is the module itself)
    names: dict[str, str] = field(default_factory=dict)


@dataclass
class FunctionNode(_Dictable):
    id: str
    name: str
    qualname: str
    line_start: int
    line_end: int
    steps: list[Step] = field(default_factory=list)
    edges: list[StepEdge] = field(default_factory=list)
    calls: list[CallRef] = field(default_factory=list)


@dataclass
class FileNode(_Dictable):
    path: str
    line_count: int
    functions: list[FunctionNode] = field(default_factory=list)
    imports: list[ImportRef] = field(default_factory=list)
    parse_error: str | None = None


@dataclass
class FileEdge(_Dictable):
    source: str
    target: str
    kind: str  # import | call


@dataclass
class SkippedFile(_Dictable):
    path: str
    reason: str


@dataclass
class RepoModel(_Dictable):
    files: list[FileNode] = field(default_factory=list)
    file_edges: list[FileEdge] = field(default_factory=list)
    skipped: list[SkippedFile] = field(default_factory=list)


def function_source(file_text: str, fn: FunctionNode) -> str:
    """The function's lines, line_start..line_end inclusive."""
    lines = file_text.split("\n")
    return "\n".join(lines[fn.line_start - 1:fn.line_end])
