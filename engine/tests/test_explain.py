import hashlib

import pytest

from cve_engine import explain_function
from cve_engine.cache import ExplanationCache
from cve_engine.explain import PLACEHOLDER, PROMPT_VERSION
from cve_engine.llm import LLMError
from cve_engine.models import FunctionNode, Step
from fakes import SOURCE, FakeLLM, make_fn


def key(depth):
    return hashlib.sha256(f"{PROMPT_VERSION}\0{depth}\0{SOURCE}".encode()).hexdigest()


def test_explanations_keyed_by_step_ids_in_order():
    llm = FakeLLM({"steps": {"s2": "B", "s1": "A"}})
    result = explain_function(make_fn(), SOURCE, "developer", llm, None, now=0.0)
    assert list(result.items()) == [("s1", "A"), ("s2", "B")]


def test_extra_ids_dropped_and_missing_filled():
    llm = FakeLLM({"steps": {"s1": "A", "s9": "invented"}})
    result = explain_function(make_fn(), SOURCE, "developer", llm, None, now=0.0)
    assert result == {"s1": "A", "s2": PLACEHOLDER}


def test_non_string_and_blank_values_are_filled():
    llm = FakeLLM({"steps": {"s1": 42, "s2": "   "}})
    result = explain_function(make_fn(), SOURCE, "developer", llm, None, now=0.0)
    assert result == {"s1": PLACEHOLDER, "s2": PLACEHOLDER}


def test_malformed_reply_gives_placeholders_and_is_not_cached(tmp_path):
    cache = ExplanationCache(tmp_path / "c.sqlite")
    result = explain_function(make_fn(), SOURCE, "developer", FakeLLM({"oops": 1}), cache, now=0.0)
    assert result == {"s1": PLACEHOLDER, "s2": PLACEHOLDER}
    assert cache.get(key("developer")) is None


def test_llm_error_gives_placeholders(tmp_path):
    cache = ExplanationCache(tmp_path / "c.sqlite")
    result = explain_function(make_fn(), SOURCE, "developer", FakeLLM(error=True), cache, now=0.0)
    assert result == {"s1": PLACEHOLDER, "s2": PLACEHOLDER}
    assert cache.get(key("developer")) is None


def test_second_call_uses_cache(tmp_path):
    cache = ExplanationCache(tmp_path / "c.sqlite")
    llm = FakeLLM({"steps": {"s1": "A", "s2": "B"}})
    first = explain_function(make_fn(), SOURCE, "developer", llm, cache, now=5.0)
    second = explain_function(make_fn(), SOURCE, "developer", llm, cache, now=6.0)
    assert first == second == {"s1": "A", "s2": "B"}
    assert len(llm.calls) == 1
    assert cache.get(key("developer")) == {"s1": "A", "s2": "B"}


def test_depth_is_part_of_cache_key(tmp_path):
    cache = ExplanationCache(tmp_path / "c.sqlite")
    llm = FakeLLM({"steps": {"s1": "A", "s2": "B"}})
    explain_function(make_fn(), SOURCE, "beginner", llm, cache, now=0.0)
    explain_function(make_fn(), SOURCE, "developer", llm, cache, now=0.0)
    assert len(llm.calls) == 2
    assert llm.calls[0][0] != llm.calls[1][0]  # depth changes the instructions


def test_prompt_contains_numbered_lines_and_step_list():
    llm = FakeLLM({"steps": {}})
    explain_function(make_fn(line_start=10), SOURCE, "developer", llm, None, now=0.0)
    user = llm.calls[0][1]
    assert "10 | def f(x):" in user
    assert "13 |     return z" in user
    assert "s1 | block | lines 11-12" in user
    assert "s2 | return | lines 13-13" in user


def test_zero_steps_returns_empty_without_llm_call():
    llm = FakeLLM({"steps": {}})
    fn = FunctionNode("a.py::f", "f", "f", 1, 1, [], [], [])
    assert explain_function(fn, "def f(): ...", "developer", llm, None, now=0.0) == {}
    assert llm.calls == []


def test_unknown_depth_is_rejected():
    with pytest.raises(ValueError):
        explain_function(make_fn(), SOURCE, "expert", FakeLLM({"steps": {}}), None, now=0.0)


def test_reply_with_no_usable_explanations_is_not_cached(tmp_path):
    cache = ExplanationCache(tmp_path / "c.sqlite")
    explain_function(make_fn(), SOURCE, "developer", FakeLLM({"steps": {}}), cache, now=0.0)
    assert cache.get(key("developer")) is None


# -- final review I8 ------------------------------------------------------------

def test_very_long_function_is_not_sent_to_the_llm():
    from cve_engine.explain import MAX_SOURCE_CHARS, TOO_LONG
    llm = FakeLLM({"steps": {"s1": "A", "s2": "B"}})
    result = explain_function(make_fn(), "x" * (MAX_SOURCE_CHARS + 1), "developer", llm, None, now=0.0)
    assert result == {"s1": TOO_LONG, "s2": TOO_LONG}
    assert llm.calls == []


# -- one line ------------------------------------------------------------------
from cve_engine import explain_line
from cve_engine.explain import BLANK_LINE, COMMENT_LINE, LOGIC_RULES, PLACEHOLDER_LINE, STE_RULES


def test_line_prompt_marks_the_target_and_uses_ste():
    llm = FakeLLM({"explanation": "Adds 1 to x. Stores the result in y."})
    out = explain_line(make_fn(), SOURCE, 11, "developer", llm, None, now=0.0)
    assert out == "Adds 1 to x. Stores the result in y."
    system, user = llm.calls[0]
    assert ">> 11 |     y = x + 1" in user
    assert "   12 |     z = y * 2" in user
    assert "ASD-STE100" in system and STE_RULES in system and LOGIC_RULES in system


def test_line_blank_and_comment_need_no_model():
    src = "def f(x):\n\n    # note\n    return x"
    fn = make_fn()
    llm = FakeLLM({"explanation": "x"})
    assert explain_line(fn, src, 11, "developer", llm, None, 0.0) == BLANK_LINE
    assert explain_line(fn, src, 12, "developer", llm, None, 0.0) == COMMENT_LINE
    assert llm.calls == []


def test_line_outside_function_is_rejected():
    with pytest.raises(ValueError):
        explain_line(make_fn(), SOURCE, 99, "developer", FakeLLM({}), None, 0.0)


def test_line_bad_reply_and_error_give_placeholder_and_cache_works(tmp_path):
    assert explain_line(make_fn(), SOURCE, 11, "developer", FakeLLM({"x": 1}), None, 0.0) == PLACEHOLDER_LINE
    assert explain_line(make_fn(), SOURCE, 11, "developer", FakeLLM(error=True), None, 0.0) == PLACEHOLDER_LINE
    cache = ExplanationCache(tmp_path / "c.db")
    llm = FakeLLM({"explanation": "A."})
    explain_line(make_fn(), SOURCE, 11, "developer", llm, cache, 0.0)
    explain_line(make_fn(), SOURCE, 11, "developer", llm, cache, 0.0)
    assert len(llm.calls) == 1


def test_line_context_is_limited_for_long_functions():
    src = "def f():\n" + "\n".join(f"    a{i} = {i}" for i in range(200))
    fn = FunctionNode("a.py::f", "f", "f", 1, 201, [Step("s1", "block", "", 2, 201)], [], [])
    llm = FakeLLM({"explanation": "A."})
    explain_line(fn, src, 60, "developer", llm, None, 0.0)
    user = llm.calls[0][1]
    assert "a10 = 10" not in user and ">> 60 |     a58 = 58" in user
    assert "    1 | def f():" in user or "   1 | def f():" in user


def test_step_prompt_asks_for_logic_not_summaries():
    llm = FakeLLM({"steps": {"s1": "A", "s2": "B"}})
    explain_function(make_fn(), SOURCE, "developer", llm, None, now=0.0)
    system = llm.calls[0][0]
    assert LOGIC_RULES in system and STE_RULES in system


def test_short_function_is_sent_whole_for_a_line():
    llm = FakeLLM({"explanation": "A."})
    explain_line(make_fn(), SOURCE, 11, "developer", llm, None, 0.0)
    user = llm.calls[0][1]
    assert "10 | def f(x):" in user and "13 |     return z" in user


# -- long functions are split; ranges ------------------------------------------
from cve_engine import explain_lines
from cve_engine.explain import CHUNK_CHARS, RANGE_TOO_LONG


class PerStepLLM:
    """Answers every listed step, or fails for requests that mention a given step."""
    def __init__(self, fail_on=None):
        self.calls, self.fail_on = [], fail_on

    def complete_json(self, system, user):
        import re
        self.calls.append((system, user))
        ids = re.findall(r"^(s\d+) \|", user, flags=re.M)
        if self.fail_on and self.fail_on in ids:
            raise LLMError("too big")
        return {"steps": {i: f"text {i}" for i in ids}}


def long_fn(n_steps=30, lines_per_step=20):
    body, steps, ln = ["def big():"], [], 2
    for k in range(n_steps):
        steps.append(Step(f"s{k + 1}", "block", "", ln, ln + lines_per_step - 1))
        body += [f"    v{k}_{j} = compute_something_long_{j}(v{k}, 'padding text to make it long')"
                 for j in range(lines_per_step)]
        ln += lines_per_step
    src = "\n".join(body)
    return FunctionNode("a.py::big", "big", "big", 1, ln - 1, steps, [], []), src


def test_long_function_is_split_into_small_requests(tmp_path):
    fn, src = long_fn()
    assert len(src) > CHUNK_CHARS
    llm = PerStepLLM()
    out = explain_function(fn, src, "developer", llm, ExplanationCache(tmp_path / "c.db"), 0.0)
    assert len(llm.calls) > 1
    assert all(len(u) < CHUNK_CHARS + 2000 for _, u in llm.calls)
    assert out == {s.id: f"text {s.id}" for s in fn.steps}


def test_one_failed_part_keeps_the_others_and_is_not_cached(tmp_path):
    fn, src = long_fn()
    cache = ExplanationCache(tmp_path / "c.db")
    out = explain_function(fn, src, "developer", PerStepLLM(fail_on="s30"), cache, 0.0)
    assert out["s1"] == "text s1" and out["s30"] == PLACEHOLDER
    llm = PerStepLLM()
    explain_function(fn, src, "developer", llm, cache, 0.0)
    assert llm.calls  # not served from cache


def test_one_huge_step_is_cut_and_says_so():
    fn, src = long_fn(n_steps=1, lines_per_step=400)
    llm = PerStepLLM()
    explain_function(fn, src, "developer", llm, None, 0.0)
    assert "not shown: too long for one request" in llm.calls[0][1]


def test_range_marks_every_selected_line():
    llm = FakeLLM({"explanation": "Sets `y`. Doubles it."})
    out = explain_lines(make_fn(), SOURCE, 11, 12, "developer", llm, None, 0.0)
    assert out == "Sets `y`. Doubles it."
    system, user = llm.calls[0]
    assert ">> 11 |" in user and ">> 12 |" in user and ">> 13 |" not in user
    assert "as a whole" in system and STE_RULES in system


def test_range_of_one_line_is_a_line_and_bad_ranges_fail():
    llm = FakeLLM({"explanation": "A."})
    assert explain_lines(make_fn(), SOURCE, 11, 11, "developer", llm, None, 0.0) == "A."
    with pytest.raises(ValueError):
        explain_lines(make_fn(), SOURCE, 12, 99, "developer", llm, None, 0.0)


def test_very_long_range_is_refused_without_a_call():
    fn, src = long_fn()
    llm = PerStepLLM()
    assert explain_lines(fn, src, fn.line_start, fn.line_end, "developer", llm, None, 0.0) == RANGE_TOO_LONG
    assert llm.calls == []


# -- tolerant replies ----------------------------------------------------------
from cve_engine.llm import NotJSON, parse_json_object


class TextLLM:
    def __init__(self, text):
        self.text, self.calls = text, []

    def complete_json(self, system, user):
        self.calls.append((system, user))
        return parse_json_object(self.text)


def test_parse_json_tolerates_fences_extra_text_and_raw_newlines():
    assert parse_json_object('Sure!\n```json\n{"explanation": "A."}\n```\nHope {this} helps') == {"explanation": "A."}
    assert parse_json_object('{"explanation": "A.\nB."}') == {"explanation": "A.\nB."}
    assert parse_json_object('note {not json} then {"a": 1}') == {"a": 1}
    with pytest.raises(NotJSON):
        parse_json_object("Applies softmax to the logits.")


def test_plain_sentence_reply_is_used_for_a_line():
    out = explain_line(make_fn(), SOURCE, 11, "developer", TextLLM("Adds 1 to `x`. Stores it in `y`."), None, 0.0)
    assert out == "Adds 1 to `x`. Stores it in `y`."


def test_other_key_name_is_accepted_for_a_line():
    out = explain_line(make_fn(), SOURCE, 11, "developer", FakeLLM({"line_11": "Adds 1."}), None, 0.0)
    assert out == "Adds 1."


def test_steps_reply_without_wrapper_is_accepted():
    out = explain_function(make_fn(), SOURCE, "developer", FakeLLM({"s1": "A", "s2": "B"}), None, 0.0)
    assert out == {"s1": "A", "s2": "B"}
