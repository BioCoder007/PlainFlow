"""Human-reviewed records and what can be made from them.

A record is created when a developer accepts or corrects an explanation, or
confirms or dismisses a flagged mismatch. Each record carries the code it is
about, so it stays usable after the repo session is gone. From records:
- training data for models (raw records, or chat-format examples);
- an onboarding walkthrough for people (Markdown).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from .explain import format_function_for_prompt
from .models import FunctionNode, function_source

MAX_CORRECTION_CHARS = 2000
MAX_INTENT_CHARS = 1000
MAX_REVIEWER_CHARS = 80
MAX_FUNCTION_CHARS = 200_000
_DEPTHS = ("beginner", "developer")


def source_hash(function_source_text: str) -> str:
    return hashlib.sha256(function_source_text.encode()).hexdigest()


def _base(kind: str, file_path: str, fn: FunctionNode, file_text: str, step_id: str,
          model: dict | None, reviewed_at: str, reviewer: str | None) -> dict:
    step = next((s for s in fn.steps if s.id == step_id), None)
    if step is None:
        raise ValueError("Unknown step.")
    reviewer = (reviewer or "").strip() or None
    if reviewer and len(reviewer) > MAX_REVIEWER_CHARS:
        raise ValueError("Keep the reviewer name under 80 characters.")
    lines = file_text.split("\n")
    return {
        "type": kind,
        "reviewed_at": reviewed_at,
        "file": file_path,
        "function": fn.qualname,
        "function_start_line": fn.line_start,
        "function_source": function_source(file_text, fn),
        "step": {
            "id": step.id, "kind": step.kind,
            "line_start": step.line_start, "line_end": step.line_end,
            "code": "\n".join(lines[step.line_start - 1:step.line_end]),
        },
        "model": model,
        "reviewer": reviewer,
    }


def explanation_record(file_path: str, fn: FunctionNode, file_text: str, step_id: str,
                       depth: str, model_explanation: str, verdict: str,
                       corrected: str | None, model: dict | None, reviewed_at: str,
                       reviewer: str | None = None) -> dict:
    """A developer accepted the model's explanation of a step, or corrected it."""
    record = _base("explanation", file_path, fn, file_text, step_id, model, reviewed_at, reviewer)
    if depth not in _DEPTHS:
        raise ValueError("Unknown depth.")
    if verdict not in ("accepted", "corrected"):
        raise ValueError("Unknown verdict.")
    model_explanation = (model_explanation or "").strip()
    if not model_explanation:
        raise ValueError("There is no explanation to review.")
    final = model_explanation
    if verdict == "corrected":
        final = (corrected or "").strip()
        if not final:
            raise ValueError("Write the corrected explanation.")
        if len(final) > MAX_CORRECTION_CHARS:
            raise ValueError("Keep the correction under 2000 characters.")
    model_field, reviewer_field = record.pop("model"), record.pop("reviewer")
    record.update(depth=depth, model=model_field, reviewer=reviewer_field,
                  model_explanation=model_explanation,
                  verdict=verdict, final_explanation=final)
    return record


def mismatch_record(file_path: str, fn: FunctionNode, file_text: str, step_id: str,
                    intent: str, model_reason: str, verdict: str,
                    model: dict | None, reviewed_at: str,
                    reviewer: str | None = None) -> dict:
    """A developer confirmed a flagged mismatch as a real issue, or dismissed it."""
    record = _base("mismatch", file_path, fn, file_text, step_id, model, reviewed_at, reviewer)
    if verdict not in ("confirmed", "dismissed"):
        raise ValueError("Unknown verdict.")
    intent = (intent or "").strip()
    if not intent or len(intent) > MAX_INTENT_CHARS:
        raise ValueError("There is no description to review against.")
    model_reason = (model_reason or "").strip()
    if not model_reason:
        raise ValueError("There is no mismatch to review.")
    record.update(intent=intent, model_reason=model_reason, verdict=verdict)
    return record


def record_key(record: dict) -> str:
    """One review per step of a given piece of code (and depth, or description).
    Reviewing again replaces the earlier verdict."""
    variant = record["depth"] if record["type"] == "explanation" else record["intent"]
    raw = "\0".join([record["type"], record["function_source"], record["step"]["id"], variant])
    return hashlib.sha256(raw.encode()).hexdigest()


# -- sharing reviews across a team ---------------------------------------------

def _is_text(value, limit: int, allow_empty: bool = False) -> bool:
    return isinstance(value, str) and len(value) <= limit and (allow_empty or value.strip() != "")


def validate_record(record) -> dict:
    """Check a record read from a teammate's export. Raises ValueError if it is
    not a well-formed review; nothing in it is ever executed."""
    if not isinstance(record, dict):
        raise ValueError("Not a review record.")
    kind = record.get("type")
    verdicts = {"explanation": ("accepted", "corrected"), "mismatch": ("confirmed", "dismissed")}
    if kind not in verdicts or record.get("verdict") not in verdicts[kind]:
        raise ValueError("Unknown review type or verdict.")
    step = record.get("step")
    ok = (
        _is_text(record.get("reviewed_at"), 40)
        and _is_text(record.get("file"), 1000)
        and _is_text(record.get("function"), 1000)
        and isinstance(record.get("function_start_line"), int)
        and _is_text(record.get("function_source"), MAX_FUNCTION_CHARS)
        and isinstance(step, dict)
        and _is_text(step.get("id"), 20) and _is_text(step.get("kind"), 20)
        and isinstance(step.get("line_start"), int) and isinstance(step.get("line_end"), int)
        and _is_text(step.get("code"), MAX_FUNCTION_CHARS, allow_empty=True)
        and (record.get("reviewer") is None or _is_text(record["reviewer"], MAX_REVIEWER_CHARS))
        and (record.get("model") is None or isinstance(record["model"], dict))
    )
    if ok and kind == "explanation":
        ok = (record.get("depth") in _DEPTHS
              and _is_text(record.get("model_explanation"), MAX_CORRECTION_CHARS * 5)
              and _is_text(record.get("final_explanation"), MAX_CORRECTION_CHARS * 5))
    elif ok:
        ok = (_is_text(record.get("intent"), MAX_INTENT_CHARS)
              and _is_text(record.get("model_reason"), MAX_CORRECTION_CHARS * 5))
    if not ok:
        raise ValueError("The review record is incomplete or damaged.")
    return record


@dataclass
class MergeResult:
    records: dict[str, dict] = field(default_factory=dict)  # key -> record, after the merge
    added: int = 0       # reviews this side did not have
    updated: int = 0     # replaced by a newer verdict from the file
    kept: int = 0        # this side's verdict was the same or newer
    conflicts: int = 0   # two people reached different verdicts on the same step


def _outcome(record: dict) -> tuple:
    return (record["verdict"], record.get("final_explanation"))


def merge_reviews(existing: dict[str, dict], incoming: list[dict]) -> MergeResult:
    """Combine a teammate's reviews with this side's. One verdict per step: the
    newer one wins. Disagreements between different reviewers are counted so
    the team knows they happened."""
    result = MergeResult(records=dict(existing))
    for record in incoming:
        key = record_key(record)
        current = result.records.get(key)
        if current is None:
            result.records[key] = record
            result.added += 1
            continue
        if (_outcome(current) != _outcome(record)
                and current.get("reviewer") != record.get("reviewer")):
            result.conflicts += 1
        if record["reviewed_at"] > current["reviewed_at"]:
            result.records[key] = record
            result.updated += 1
        else:
            result.kept += 1
    return result


# -- training data for models --------------------------------------------------

def _fn_for_prompt(record: dict) -> str:
    step = record["step"]
    fn = FunctionNode(
        id="", name=record["function"], qualname=record["function"],
        line_start=record["function_start_line"],
        line_end=record["function_start_line"] + record["function_source"].count("\n"))
    numbered = format_function_for_prompt(fn, record["function_source"]).split("\n\nSteps", 1)[0]
    return f"{numbered}\n\nStep: lines {step['line_start']}-{step['line_end']} ({step['kind']})"


def chat_example(record: dict) -> dict:
    """One fine-tuning example in the common chat format (system / user / assistant).
    The assistant turn is what a human approved, never an unreviewed model reply."""
    if record["type"] == "explanation":
        audience = ("someone new to programming" if record["depth"] == "beginner"
                    else "a working Python developer")
        system = (f"Explain what the given lines of a Python function do, for {audience}, "
                  "in at most two sentences. Describe only what the code does.")
        user = _fn_for_prompt(record)
        answer = record["final_explanation"]
    else:
        system = ("Decide whether the given lines of a Python function differ from the "
                  "developer's description of what the function should do. Answer "
                  '"Mismatch: <reason>" or "No mismatch."')
        user = f"{_fn_for_prompt(record)}\n\nDescription: {record['intent']}"
        answer = (f"Mismatch: {record['model_reason']}" if record["verdict"] == "confirmed"
                  else "No mismatch.")
    return {"messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
        {"role": "assistant", "content": answer},
    ]}


# -- onboarding walkthrough for people -----------------------------------------

def _line_words(step: dict, capital: bool) -> str:
    a, b = step["line_start"], step["line_end"]
    words = f"line {a}" if a == b else f"lines {a} to {b}"
    return words.capitalize() if capital else words


def _fence(code: str) -> str:
    longest = max((len(run) for run in re.findall(r"`+", code)), default=0)
    return "`" * max(3, longest + 1)


def onboarding_markdown(title: str, records: list[dict]) -> str:
    """A walkthrough of every function that has reviewed explanations or confirmed
    issues. Only human-reviewed text is included."""
    functions: dict[tuple, dict] = {}
    for rec in records:
        if rec["type"] == "mismatch" and rec["verdict"] != "confirmed":
            continue
        key = (rec["file"], rec["function_start_line"], rec["function"], rec["function_source"])
        entry = functions.setdefault(key, {"explanations": {}, "issues": {}})
        step_id = rec["step"]["id"]
        bucket = entry["explanations"] if rec["type"] == "explanation" else entry["issues"]
        current = bucket.get(step_id)
        # one entry per step: prefer the developer-depth text, then the newest
        rank = (rec.get("depth") == "developer", rec["reviewed_at"])
        if current is None or rank > current[0]:
            bucket[step_id] = (rank, rec)

    out = [f"# {title}: code walkthrough", "",
           "Every explanation below was checked by a person on the team.", ""]
    if not functions:
        out.append("No reviewed explanations yet.")
        return "\n".join(out) + "\n"

    current_file = None
    for (file, start, name, source) in sorted(functions, key=lambda k: (k[0], k[1], k[2])):
        entry = functions[(file, start, name, source)]
        if file != current_file:
            out += [f"## {file}", ""]
            current_file = file
        fence = _fence(source)
        out += [f"### {name} (line {start})", "", f"{fence}python", source, fence, ""]
        notes = [(rec["step"]["line_start"], 0,
                  f"**{_line_words(rec['step'], True)}.** {rec['final_explanation']}")
                 for _, rec in entry["explanations"].values()]
        notes += [(rec["step"]["line_start"], 1,
                   f"**Reported issue at {_line_words(rec['step'], False)}.** "
                   f"Meant to: {rec['intent'].rstrip('.')}. {rec['model_reason']}")
                  for _, rec in entry["issues"].values()]
        for _, _, text in sorted(notes):
            out += [text, ""]
    return "\n".join(out).rstrip("\n") + "\n"
