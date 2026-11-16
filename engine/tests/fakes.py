"""Test doubles shared by the engine tests."""
from cve_engine.llm import LLMError
from cve_engine.models import FunctionNode, Step


class FakeLLM:
    def __init__(self, reply=None, error=False):
        self.reply = reply
        self.error = error
        self.calls = []  # (system, user)

    def complete_json(self, system, user):
        self.calls.append((system, user))
        if self.error:
            raise LLMError("boom")
        return self.reply


SOURCE = "def f(x):\n    y = x + 1\n    z = y * 2\n    return z"


def make_fn(line_start=10):
    return FunctionNode(
        "a.py::f", "f", "f", line_start, line_start + 3,
        [Step("s1", "block", "y = x + 1", line_start + 1, line_start + 2),
         Step("s2", "return", "return z", line_start + 3, line_start + 3)],
        [], [])
