import json

import pytest

from cve_engine.export import (
    merge_reviews, validate_record,
    chat_example, explanation_record, mismatch_record, onboarding_markdown, record_key,
    source_hash,
)
from cve_engine.models import FunctionNode, Step

FILE_TEXT = "import os\n\ndef f(x):\n    y = x + 1\n    z = y * 2\n    return z\n"
FN = FunctionNode("a.py::f", "f", "f", 3, 6, [
    Step("s1", "block", "y = x + 1", 4, 5), Step("s2", "return", "return z", 6, 6)], [], [])
NOW = "2026-11-14T10:00:00+00:00"
MODEL = {"provider": "local", "model": "llama3"}


def explain(**kw):
    args = dict(file_path="a.py", fn=FN, file_text=FILE_TEXT, step_id="s1", depth="developer",
                model_explanation="Adds one, then doubles.", verdict="accepted", corrected=None,
                model=MODEL, reviewed_at=NOW)
    args.update(kw)
    return explanation_record(**args)


def mismatch(**kw):
    args = dict(file_path="a.py", fn=FN, file_text=FILE_TEXT, step_id="s2", intent="returns y",
                model_reason="Returns z, not y.", verdict="confirmed", model=MODEL, reviewed_at=NOW)
    args.update(kw)
    return mismatch_record(**args)


def test_explanation_record_is_self_contained():
    rec = explain()
    assert rec == {
        "type": "explanation", "reviewed_at": NOW, "file": "a.py", "function": "f",
        "function_start_line": 3,
        "function_source": "def f(x):\n    y = x + 1\n    z = y * 2\n    return z",
        "step": {"id": "s1", "kind": "block", "line_start": 4, "line_end": 5,
                 "code": "    y = x + 1\n    z = y * 2"},
        "depth": "developer", "model": MODEL, "reviewer": None,
        "model_explanation": "Adds one, then doubles.",
        "verdict": "accepted", "final_explanation": "Adds one, then doubles.",
    }
    json.dumps(rec)


def test_corrected_explanation_keeps_both_texts():
    rec = explain(verdict="corrected", corrected="  Adds 1 to x and doubles the result.  ")
    assert rec["model_explanation"] == "Adds one, then doubles."
    assert rec["final_explanation"] == "Adds 1 to x and doubles the result."


def test_mismatch_record():
    rec = mismatch()
    assert rec["type"] == "mismatch" and rec["intent"] == "returns y"
    assert rec["model_reason"] == "Returns z, not y." and rec["verdict"] == "confirmed"
    assert rec["step"]["code"] == "    return z"
    assert mismatch(verdict="dismissed")["verdict"] == "dismissed"


@pytest.mark.parametrize("kw,message", [
    (dict(step_id="s9"), "Unknown step."),
    (dict(verdict="maybe"), "Unknown verdict."),
    (dict(depth="expert"), "Unknown depth."),
    (dict(model_explanation="  "), "There is no explanation to review."),
    (dict(verdict="corrected", corrected=" "), "Write the corrected explanation."),
    (dict(verdict="corrected", corrected="x" * 2001), "Keep the correction under 2000 characters."),
])
def test_explanation_record_rejects_bad_input(kw, message):
    with pytest.raises(ValueError) as exc:
        explain(**kw)
    assert str(exc.value) == message


@pytest.mark.parametrize("kw,message", [
    (dict(step_id="s9"), "Unknown step."),
    (dict(verdict="accepted"), "Unknown verdict."),
    (dict(intent=" "), "There is no description to review against."),
    (dict(model_reason=""), "There is no mismatch to review."),
])
def test_mismatch_record_rejects_bad_input(kw, message):
    with pytest.raises(ValueError) as exc:
        mismatch(**kw)
    assert str(exc.value) == message


def test_record_key_is_stable_per_step_and_changes_with_the_code():
    assert record_key(explain()) == record_key(explain(verdict="corrected", corrected="x"))
    assert record_key(explain()) != record_key(explain(step_id="s2"))
    assert record_key(explain()) != record_key(explain(depth="beginner"))
    assert record_key(explain()) != record_key(mismatch(step_id="s1"))
    assert record_key(mismatch()) != record_key(mismatch(intent="returns x"))
    other = FILE_TEXT.replace("x + 1", "x + 2")
    assert record_key(explain()) != record_key(explain(file_text=other))
    assert source_hash(explain()["function_source"]) != source_hash(explain(file_text=other)["function_source"])


def test_chat_example_for_an_explanation_uses_the_final_text():
    ex = chat_example(explain(verdict="corrected", corrected="Adds 1 and doubles."))
    roles = [m["role"] for m in ex["messages"]]
    assert roles == ["system", "user", "assistant"]
    user = ex["messages"][1]["content"]
    assert "3 | def f(x):" in user and "lines 4-5" in user
    assert ex["messages"][2]["content"] == "Adds 1 and doubles."


def test_chat_example_for_a_mismatch_states_the_human_verdict():
    confirmed = chat_example(mismatch())
    dismissed = chat_example(mismatch(verdict="dismissed"))
    assert "returns y" in confirmed["messages"][1]["content"]
    assert confirmed["messages"][2]["content"] == "Mismatch: Returns z, not y."
    assert dismissed["messages"][2]["content"] == "No mismatch."


def test_onboarding_markdown_lists_reviewed_functions_with_their_steps():
    md = onboarding_markdown("my-repo", [explain(), mismatch()])
    assert md.startswith("# my-repo: code walkthrough\n")
    assert "## a.py" in md and "### f (line 3)" in md
    assert "```python\ndef f(x):" in md
    assert "**Lines 4 to 5.** Adds one, then doubles." in md
    assert "**Reported issue at line 6.** Meant to: returns y. Returns z, not y." in md


def test_onboarding_markdown_leaves_out_dismissed_mismatches_and_handles_no_reviews():
    md = onboarding_markdown("r", [mismatch(verdict="dismissed")])
    assert "Reported issue" not in md
    assert "No reviewed explanations yet." in onboarding_markdown("r", [])


def test_code_containing_a_fence_cannot_break_out_of_the_code_block():
    text = 'def f(x):\n    y = """\n```\n"""\n    return y\n'
    fn = FunctionNode("a.py::f", "f", "f", 1, 5, [Step("s1", "block", "y", 2, 4)], [], [])
    rec = explain(fn=fn, file_text=text)
    md = onboarding_markdown("r", [rec])
    assert "````python\n" in md


# -- team reviews ------------------------------------------------------------------

def test_reviewer_name_is_recorded_trimmed():
    assert explain(reviewer="  Sara  ")["reviewer"] == "Sara"
    assert mismatch(reviewer="Bilal")["reviewer"] == "Bilal"
    assert explain(reviewer="   ")["reviewer"] is None
    with pytest.raises(ValueError) as exc:
        explain(reviewer="x" * 81)
    assert str(exc.value) == "Keep the reviewer name under 80 characters."


def by_key(*records):
    return {record_key(r): r for r in records}


def test_merge_adds_reviews_that_are_new():
    mine = by_key(explain(reviewer="Me"))
    result = merge_reviews(mine, [mismatch(reviewer="Sara")])
    assert (result.added, result.updated, result.kept, result.conflicts) == (1, 0, 0, 0)
    assert len(result.records) == 2


def test_merge_takes_the_newer_verdict_and_counts_the_disagreement():
    mine = by_key(explain(reviewer="Me", reviewed_at="2026-11-14T10:00:00+00:00"))
    theirs = explain(reviewer="Sara", verdict="corrected", corrected="Better text.",
                     reviewed_at="2026-11-14T12:00:00+00:00")
    result = merge_reviews(mine, [theirs])
    assert (result.added, result.updated, result.kept, result.conflicts) == (0, 1, 0, 1)
    assert list(result.records.values())[0]["final_explanation"] == "Better text."


def test_merge_keeps_mine_when_it_is_newer_and_still_counts_the_disagreement():
    mine = by_key(explain(reviewer="Me", verdict="corrected", corrected="My text.",
                          reviewed_at="2026-11-14T12:00:00+00:00"))
    theirs = explain(reviewer="Sara", reviewed_at="2026-11-14T10:00:00+00:00")
    result = merge_reviews(mine, [theirs])
    assert (result.added, result.updated, result.kept, result.conflicts) == (0, 0, 1, 1)
    assert list(result.records.values())[0]["final_explanation"] == "My text."


def test_merge_of_the_same_file_twice_changes_nothing():
    mine = by_key(explain(reviewer="Me"), mismatch(reviewer="Me"))
    result = merge_reviews(mine, [explain(reviewer="Me"), mismatch(reviewer="Me")])
    assert (result.added, result.updated, result.kept, result.conflicts) == (0, 0, 2, 0)


def test_agreeing_reviews_from_two_people_are_not_a_conflict():
    mine = by_key(explain(reviewer="Me", reviewed_at="2026-11-14T10:00:00+00:00"))
    result = merge_reviews(mine, [explain(reviewer="Sara", reviewed_at="2026-11-14T12:00:00+00:00")])
    assert (result.updated, result.conflicts) == (1, 0)


def test_merge_does_not_change_the_dictionary_it_was_given():
    mine = by_key(explain(reviewer="Me"))
    merge_reviews(mine, [mismatch(reviewer="Sara")])
    assert len(mine) == 1


def test_validate_record_accepts_exported_records():
    for rec in (explain(reviewer="Me"), mismatch()):
        assert validate_record(json.loads(json.dumps(rec))) == rec


@pytest.mark.parametrize("change", [
    lambda r: r.pop("function_source"),
    lambda r: r.update(type="other"),
    lambda r: r.update(verdict="confirmed"),         # not valid for an explanation
    lambda r: r.update(step="s1"),
    lambda r: r["step"].update(line_start="4"),
    lambda r: r.update(final_explanation=""),
    lambda r: r.update(function_source="x" * 200_001),
    lambda r: r.update(reviewed_at=5),
    lambda r: r.update(reviewer=["a"]),
])
def test_validate_record_rejects_damaged_records(change):
    rec = explain()
    change(rec)
    with pytest.raises(ValueError):
        validate_record(rec)


def test_validate_record_rejects_things_that_are_not_records():
    for bad in (None, [], "text", {"type": "explanation"}):
        with pytest.raises(ValueError):
            validate_record(bad)
