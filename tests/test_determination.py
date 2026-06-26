"""Golden-prompt tests for the determination core (no Hermes needed)."""

import json
import pathlib

import pytest

from hermes_model_router.determination import classify, Decision, TIERS

EVAL = pathlib.Path(__file__).resolve().parents[1] / "eval" / "prompts.jsonl"


def _load_eval():
    rows = []
    for line in EVAL.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            rows.append(json.loads(line))
    return rows


@pytest.mark.parametrize("row", _load_eval())
def test_eval_prompts_tier(row):
    d = classify(row["prompt"])
    assert d.tier in TIERS
    assert d.tier == row["tier"], (
        f"{row['prompt'][:60]!r} -> {d.tier} (want {row['tier']}); "
        f"score={d.tier_scores} signals={d.scores}"
    )


def test_eval_accuracy_threshold():
    rows = _load_eval()
    correct = sum(1 for r in rows if classify(r["prompt"]).tier == r["tier"])
    acc = correct / len(rows)
    assert acc >= 0.85, f"tier accuracy {acc:.0%} below 85% ({correct}/{len(rows)})"


def test_empty_prompt_is_cheap_low_confidence():
    d = classify("")
    assert d.tier == "cheap"
    assert d.confidence == 0.0
    assert d.est_tokens == 0


def test_simple_indicator_pulls_down():
    assert classify("what is the capital of France?").tier == "cheap"


def test_reasoning_marker_pushes_up():
    d = classify(
        "Prove that the algorithm terminates and analyse its worst-case "
        "time complexity, then design a more efficient approach."
    )
    assert d.tier == "reasoning"
    assert d.confidence > 0.0


def test_code_block_is_not_cheap():
    d = classify("Refactor this:\n```python\ndef f(x):\n  return x*2\n```")
    assert d.tier in ("smart", "reasoning")


def test_decision_is_serialisable():
    d = classify("design a distributed rate limiter")
    assert isinstance(d, Decision)
    blob = json.dumps(d.as_dict())
    assert "tier" in blob and "scores" in blob


def test_deterministic():
    p = "Explain why mutexes can deadlock and how to avoid it."
    assert classify(p).tier == classify(p).tier
    assert classify(p).scores == classify(p).scores
