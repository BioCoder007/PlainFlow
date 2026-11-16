import json

from cve_engine.models import (
    CallRef, FileNode, FunctionNode, RepoModel, Step, function_source,
)


def test_repo_model_to_dict_is_json_serialisable():
    step = Step("s1", "block", "x = 1", 2, 2)
    fn = FunctionNode("a.py::f", "f", "f", 1, 2, [step], [], [CallRef("g", 2)])
    model = RepoModel([FileNode("a.py", 2, [fn], [])], [], [])
    data = json.loads(json.dumps(model.to_dict()))
    assert data["files"][0]["functions"][0]["steps"][0] == {
        "id": "s1", "kind": "block", "label": "x = 1", "line_start": 2, "line_end": 2}
    assert data["files"][0]["functions"][0]["calls"][0]["target"] is None


def test_function_source_returns_inclusive_line_range():
    fn = FunctionNode("a.py::f", "f", "f", 2, 3, [], [], [])
    assert function_source("a\nb\nc\nd", fn) == "b\nc"
