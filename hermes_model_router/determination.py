"""Local, no-LLM-call complexity determination for prompt routing.

Given a prompt, decide a *tier* — ``cheap`` | ``smart`` | ``reasoning`` — using a
transparent weighted heuristic over cheap-to-compute signals. No network, no ML,
sub-millisecond. Every decision is explainable: ``Decision.scores`` records each
signal's contribution so heuristics can be tuned against the eval set.

This module is the reusable core. It has one public function — ``classify`` — and
no dependency on Hermes, so it can be unit-tested and swapped (v2: a local
embedding/ModernBERT/RouteLLM classifier) behind the same signature.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

TIERS = ("cheap", "smart", "reasoning")

# ── Signal vocabularies ──────────────────────────────────────────────────────
# Kept as module constants so the eval harness / Hermes coder can tune them.

_REASONING_MARKERS = (
    "prove", "derive", "why ", "design ", "architect",
    "root cause", "trade-off", "tradeoff", "analy", "evaluate",
    "compare", "strategy", "plan ", "reason", "explain how", "step by step",
    "edge case", "complexity", "algorithm", "concurren", "race condition",
    "consistency", "distributed", "multi-tenant", "scalab", "scale ",
    "failure mode", "event-sourc", "cqrs", "isolation", "worst-case",
)

# Imperative "do real work" verbs (excludes cheap ones like translate/define/
# list/rename/convert/draft, which are simple-task indicators instead).
_TASK_VERBS = (
    "write ", "implement", "build ", "create ", "refactor", "debug",
    "optimi", "port ", "migrate", "integrate", " add ", "generate ",
    "parse ", "render ",
)
_MULTI_STEP_MARKERS = (
    " then ", " after that", " followed by", "first,", "next,", "finally,",
    "1.", "2.", "3.", "- ", "* ",
)
# Matched as LEADING intent (prompt starts with one of these), not anywhere —
# otherwise "linked list" / "when combined" would falsely look like simple tasks.
_SIMPLE_INDICATORS = (
    "what is", "what are", "who is", "who was", "when did", "when is",
    "where is", "define ", "translate", "summari", "tldr", "spell ",
    "convert ", "rename ", "list ", "fix typo", "format ", "how do you say",
    "say ", "give me a list", "name the", "name three",
)
_TECHNICAL_TERMS = (
    "kubernetes", "regex", "sql", "async", "mutex", "tensor", "gradient",
    "oauth", "jwt", "rpc", "grpc", "ffi", "bitmask", "b-tree", "lru",
    "idempoten", "transaction", "deadlock", "throughput", "latency",
    "proof", "theorem", "invariant", "monad", "borrow checker",
)
_CODE_PATTERNS = (
    re.compile(r"```"),                       # fenced code block
    re.compile(r"\bdef \w+\("),               # python def
    re.compile(r"\b(function|const|let|var)\b"),
    re.compile(r"[{};]\s*$", re.MULTILINE),   # braces / semicolons
    re.compile(r"^\s*(diff --git|@@ )", re.MULTILINE),  # a diff/patch
    re.compile(r"\bclass \w+"),
)


@dataclass
class Decision:
    """The outcome of classifying a prompt. ``scores`` makes it explainable."""

    tier: str                                  # one of TIERS
    confidence: float                          # 0..1, derived from score margin
    est_tokens: int                            # rough input-size estimate
    scores: Dict[str, float] = field(default_factory=dict)   # signal -> contribution
    tier_scores: Dict[str, float] = field(default_factory=dict)  # tier -> total
    suggested: Optional[str] = None            # filled in by the tier map, not here

    def as_dict(self) -> Dict[str, Any]:
        return {
            "tier": self.tier,
            "confidence": round(self.confidence, 3),
            "est_tokens": self.est_tokens,
            "scores": {k: round(v, 3) for k, v in self.scores.items()},
            "tier_scores": {k: round(v, 3) for k, v in self.tier_scores.items()},
            "suggested": self.suggested,
        }


# ── Weights: how much each signal pushes toward "needs a stronger model" ──────
# Positive weight => raises complexity. Tuned against eval/prompts.jsonl.
WEIGHTS: Dict[str, float] = {
    "length": 1.0,        # long prompts tend to be harder
    "code": 1.4,          # code present => smart+ territory
    "reasoning": 2.0,     # reasoning markers are the strongest signal
    "multi_step": 1.0,    # multi-step instructions
    "technical": 1.2,     # dense technical vocabulary
    "questions": 0.4,     # many questions => more to handle
    "task_verb": 1.3,     # imperative "do real work" verbs
    "simple": -2.5,       # explicit simple-task indicators pull down hard
}

# Score thresholds mapping a final complexity score -> tier.
THRESHOLDS = {"cheap_max": 1.2, "smart_max": 4.0}


def _estimate_tokens(text: str) -> int:
    # ~4 chars/token is a good cheap approximation for English+code.
    return max(1, len(text) // 4)


def _count_hits(haystack: str, needles) -> int:
    return sum(haystack.count(n) for n in needles)


def _length_signal(text: str, est_tokens: int) -> float:
    # Saturating: 0 at tiny, ~1 around 250 tokens, ~2 past ~1.2k tokens.
    if est_tokens < 40:
        return 0.0
    if est_tokens < 250:
        return 1.0
    if est_tokens < 1200:
        return 1.6
    return 2.2


def _code_signal(text: str) -> float:
    hits = sum(1 for p in _CODE_PATTERNS if p.search(text))
    return min(hits / 2.0, 2.0)  # 0, .5, 1, 1.5, 2 …


def compute_signals(text: str) -> Dict[str, float]:
    """Return the raw (pre-weight) strength of each signal in ``[0, ~]``."""
    lower = text.lower()
    est_tokens = _estimate_tokens(text)
    return {
        "length": _length_signal(text, est_tokens),
        "code": _code_signal(text),
        "reasoning": min(_count_hits(lower, _REASONING_MARKERS), 3) / 1.0,
        "multi_step": min(_count_hits(lower, _MULTI_STEP_MARKERS), 4) / 2.0,
        "technical": min(_count_hits(lower, _TECHNICAL_TERMS), 4) / 1.5,
        "questions": min(text.count("?"), 4) / 2.0,
        "task_verb": min(_count_hits(lower, _TASK_VERBS), 2) / 1.5,
        "simple": 1.0 if lower.lstrip("\"'` \t").startswith(_SIMPLE_INDICATORS) else 0.0,
    }


def classify(text: str, ctx: Optional[Dict[str, Any]] = None) -> Decision:
    """Classify ``text`` into a routing tier. Pure, local, deterministic."""
    text = (text or "").strip()
    est_tokens = _estimate_tokens(text)
    if not text:
        return Decision(tier="cheap", confidence=0.0, est_tokens=0,
                        scores={}, tier_scores={t: 0.0 for t in TIERS})

    signals = compute_signals(text)
    contributions = {k: signals[k] * WEIGHTS[k] for k in signals}
    score = sum(contributions.values())

    # Map the continuous score onto three tiers with soft margins for confidence.
    if score <= THRESHOLDS["cheap_max"]:
        tier = "cheap"
        # distance to the nearest boundary, normalised
        margin = (THRESHOLDS["cheap_max"] - score) / max(THRESHOLDS["cheap_max"], 1.0)
    elif score <= THRESHOLDS["smart_max"]:
        tier = "smart"
        span = THRESHOLDS["smart_max"] - THRESHOLDS["cheap_max"]
        mid = (THRESHOLDS["cheap_max"] + THRESHOLDS["smart_max"]) / 2
        margin = 1.0 - abs(score - mid) / (span / 2)
    else:
        tier = "reasoning"
        margin = min((score - THRESHOLDS["smart_max"]) / THRESHOLDS["smart_max"], 1.0)

    confidence = max(0.0, min(1.0, margin))
    tier_scores = {
        "cheap": max(0.0, THRESHOLDS["cheap_max"] - score),
        "smart": max(0.0, 2.0 - abs(score - 3.0)),
        "reasoning": max(0.0, score - THRESHOLDS["smart_max"]),
    }
    return Decision(
        tier=tier,
        confidence=confidence,
        est_tokens=est_tokens,
        scores=contributions,
        tier_scores=tier_scores,
    )
