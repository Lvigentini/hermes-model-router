"""Tests for tier resolution and the llm_request middleware (no Hermes needed)."""

from hermes_model_router.config import RouterConfig
from hermes_model_router.determination import classify, Decision
from hermes_model_router.middleware import (
    make_llm_request_middleware, make_model_request_middleware, _latest_user_text,
)
from hermes_model_router.tiers import resolve_route


def _cfg(**over):
    base = dict(
        enabled=True, gate_confidence=0.0, respect_explicit_model=True,
        same_provider_only=True,
        tiers={
            "cheap": {"provider": "kimi-coding", "model": "kimi-for-coding"},
            "smart": {"provider": "kimi-coding", "model": "kimi-smart"},
            "reasoning": {"provider": "anthropic", "model": "claude-opus-4-8"},
        },
    )
    base.update(over)
    return RouterConfig.from_mapping(base)


# ── tiers.resolve_route ──────────────────────────────────────────────────────

def test_gate_blocks_low_confidence():
    # A low-confidence decision is left untouched regardless of tier.
    cfg = _cfg(gate_confidence=0.55)
    d = Decision(tier="reasoning", confidence=0.2, est_tokens=10)
    assert resolve_route(d, cfg, current_provider="kimi-coding", current_model="x") is None


def test_confident_decision_routes():
    cfg = _cfg(gate_confidence=0.55)
    d = Decision(tier="reasoning", confidence=0.9, est_tokens=10)
    r = resolve_route(d, cfg, current_provider="kimi-coding", current_model="kimi-for-coding")
    assert r is not None and r.model == "claude-opus-4-8" and r.cross_provider


def test_no_route_when_already_on_target():
    cfg = _cfg()
    d = classify("what is the capital of France?")  # cheap
    r = resolve_route(d, cfg, current_provider="kimi-coding", current_model="kimi-for-coding")
    assert r is None  # already on the cheap target


def test_same_provider_swap_is_allowed():
    cfg = _cfg()
    d = classify("Write a SQL query for the second highest salary per department.")  # smart
    r = resolve_route(d, cfg, current_provider="kimi-coding", current_model="kimi-for-coding")
    assert r is not None and r.model == "kimi-smart" and not r.cross_provider


def test_cross_provider_suppressed_by_default():
    cfg = _cfg()
    d = classify("Prove termination and analyse worst-case complexity, then redesign.")  # reasoning
    r = resolve_route(d, cfg, current_provider="kimi-coding", current_model="kimi-for-coding")
    assert r is not None and r.cross_provider and "suppressed" in r.reason


# ── middleware ───────────────────────────────────────────────────────────────

def test_latest_user_text_chat_and_responses_shapes():
    assert _latest_user_text({"messages": [{"role": "user", "content": "hi"}]}) == "hi"
    assert _latest_user_text({"input": [{"role": "user", "content": "yo"}]}) == "yo"
    multimodal = {"messages": [{"role": "user", "content": [{"type": "text", "text": "abc"}]}]}
    assert _latest_user_text(multimodal) == "abc"


def test_middleware_rewrites_model_same_provider():
    mw = make_llm_request_middleware(_cfg())
    req = {"model": "kimi-for-coding",
           "messages": [{"role": "user", "content":
                         "Write a SQL query for the second highest salary per department."}]}
    out = mw(request=req, provider="kimi-coding", model="kimi-for-coding")
    assert out and out["request"]["model"] == "kimi-smart"
    # original request object is not mutated in place
    assert req["model"] == "kimi-for-coding"


def test_middleware_passes_through_cross_provider():
    mw = make_llm_request_middleware(_cfg())
    req = {"model": "kimi-for-coding",
           "messages": [{"role": "user", "content":
                         "Prove termination and analyse worst-case complexity, then redesign it."}]}
    out = mw(request=req, provider="kimi-coding", model="kimi-for-coding")
    # cross-provider => no request rewrite, just a trace reason
    assert out is not None and "request" not in out


def test_resolve_route_allows_cross_provider_when_permitted():
    cfg = _cfg()
    d = classify("Prove termination and analyse worst-case complexity, then redesign it.")  # reasoning
    r = resolve_route(d, cfg, current_provider="kimi-coding", current_model="kimi-for-coding",
                      allow_cross_provider=True)
    assert r is not None and r.cross_provider and r.provider == "anthropic"
    assert "suppressed" not in r.reason


# ── model_request middleware (the pre-model-selection seam consumer) ──────────

def test_model_request_crosses_provider():
    mw = make_model_request_middleware(_cfg())
    req = {"model": "kimi-for-coding", "provider": "kimi-coding",
           "base_url": "https://api.kimi.com/coding", "api_mode": "chat_completions"}
    out = mw(request=req, user_message="Prove termination and analyse worst-case complexity, then redesign it.")
    assert out is not None
    r = out["request"]
    assert r["provider"] == "anthropic" and r["model"] == "claude-opus-4-8"
    # stale endpoint fields cleared so the gateway re-resolves them
    assert r["base_url"] is None and r["api_mode"] is None


def test_model_request_noop_on_easy_prompt():
    mw = make_model_request_middleware(_cfg())
    req = {"model": "kimi-for-coding", "provider": "kimi-coding"}
    # cheap prompt → already on the cheap target → no change
    assert mw(request=req, user_message="what is the capital of France?") is None


def test_middleware_noop_on_empty_and_disabled():
    assert make_llm_request_middleware(_cfg())(request={"messages": []},
                                              provider="kimi-coding", model="x") is None
    assert make_llm_request_middleware(_cfg(enabled=False))(
        request={"messages": [{"role": "user", "content": "design a system"}]},
        provider="kimi-coding", model="x") is None
