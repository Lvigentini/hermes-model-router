# Upstream PR draft — `pre_model_selection` seam for Hermes

Target: [`NousResearch/hermes-agent`](https://github.com/NousResearch/hermes-agent) `main` (@ `8cf9d86`).
Patch: [`0001-add-pre-model-selection-seam.patch`](0001-add-pre-model-selection-seam.patch)
(`git apply` from the repo root). 2 files, +118/−6.

## Proposed PR title
`feat(gateway): pre-model-selection middleware seam for per-turn cross-provider routing`

## Problem
Plugins can change *what* a turn sends (`llm_request` middleware rewrites the request body) but not
*where* it goes: the provider, transport, and credentials are bound before any plugin code runs, and
nothing downstream re-reads them. So a plugin **cannot route a turn to a different provider** — e.g.
send an easy prompt to a cheap model and a hard one to Opus/GPT‑5.5 across providers. The only knobs
are the static primary model, the failure-driven `fallback_providers` chain, and manual `/model`.

## What this adds
A new request-middleware kind, **`model_request`**, applied at the single point where the per-turn
model/runtime is resolved in the gateway (`_resolve_turn_agent_config`), **before** credentials are
bound. Middleware receives the proposed route `{model, provider, base_url, api_mode}` plus
`user_message`, and may return `{"request": {…}}` to re-route the turn. On a **cross-provider**
re-route the gateway resolves the chosen provider's credentials via the existing
`resolve_runtime_provider(...)`, so the turn binds to the right account.

It reuses the existing middleware framework (`apply_*_request_middleware`, `VALID_MIDDLEWARE`,
`ctx.register_middleware`) — no new concepts — and is **fail-open**: any error, missing credentials, or
absent middleware keeps the session's primary route. Zero overhead when no `model_request` middleware
is registered (early `_has_middleware` return).

**Coverage — gateway *and* in-process.** The gateway routes at `_resolve_turn_agent_config` (before the
agent is built, cache-friendly). The interactive TUI / CLI / oneshot build a persistent agent and don't
hit that path, so the patch also adds an in-process seam in `agent/conversation_loop.run_conversation`:
before the first API call of a turn it runs the same `model_request` middleware and applies the choice
via the existing `agent.switch_model(...)` primitive (the one `/model` uses). It is gated to skip when
`gateway_session_key` is set, so the two never double-route. `cli.py` sets `agent._model_pinned` on a
user `/model` so the in-process router stands down on a pin (mirrors the gateway's `explicit_model`).
Crucially, `switch_model` leaves `_fallback_chain` intact, so an out-of-credits routed model still
falls back down the configured chain.

### Why middleware, not a hook
Hermes hooks are fire-and-forget observers; they can't change the route. Request middleware is the
established seam for behaviour-changing rewrites (`tool_request`, `llm_request`), so `model_request`
slots in beside them and inherits their trace/telemetry contract.

### Why the gateway turn-resolution point
`_resolve_turn_agent_config` runs **once per user turn, before the agent/transport is built**. Routing
here means the agent is constructed correctly from the start — no mid-flight provider swap, no
provider-specific message-shape reconciliation (contrast the `fallback` path, which swaps mid-loop and
must re-pad reasoning fields). It is also exactly "decide at the gateway, before the first LLM call."

## What live switching means in practice (design notes)
- **The first prompt costs no extra LLM call.** The routing decision is the middleware's; a local
  classifier (e.g. a complexity heuristic) decides in sub-ms. The *first* provider call already goes to
  the chosen model.
- **Once per user turn, not per tool-call.** The seam fires at turn resolution, so the whole tool loop
  for that message runs on one consistently-chosen backend — no mid-task provider churn.
- **Cross-provider history continuity.** A session that switches provider *between* turns sends prior
  history to the new provider. Hermes already reconciles cross-provider history for `fallback`; the same
  applies. Provider-specific prompt caching resets on a switch (expected).
- **Credentials & fail-open.** If the chosen provider isn't authenticated (`resolve_runtime_provider`
  yields no key/command), the turn keeps the primary route rather than erroring.
- **Cost is intentional.** Routing hard turns to a strong model costs more by design; a confidence gate
  in the router avoids needless switching for ambiguous prompts.
- **Explicit pins win.** When the user pins a model (`/model`, a session model override), the gateway
  tags the turn (`_explicit_model`) and passes `explicit_model=True` into the `model_request` context,
  so a well-behaved router stands down. Routers that ignore this can still override (their choice).
- **Determinism.** With a rule-based local router the decision is deterministic and inspectable
  (middleware `trace` records source + reason), which keeps routing debuggable.

## Test plan
- Unit: `model_request` middleware re-routes model+provider; `apply_model_request_middleware` returns
  `changed=False` when unregistered (mirrors existing `test_plugins.py` middleware tests).
- Gateway: `_apply_model_selection` returns `(model, runtime)` unchanged on no-op; on cross-provider
  selection, credentials are re-resolved and a missing-credential selection falls back to primary.
- Reference consumer: the [`hermes-model-router`](https://github.com/Lvigentini/hermes-model-router)
  plugin registers a `model_request` middleware backed by a local, no-LLM complexity classifier.

## Reference implementation
The consuming plugin (this repo) registers a `model_request` middleware that classifies each turn
locally (`cheap`/`smart`/`reasoning`) and re-routes accordingly — see `hermes_model_router/middleware.py`.
