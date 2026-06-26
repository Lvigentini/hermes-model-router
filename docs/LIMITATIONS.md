# Verification limit — what we can and can't do

This documents a constraint **verified against the Hermes source**, and what it means in practice for
the original routing plan. Read alongside the "Seam finding" section of [`PLAN.md`](PLAN.md).

## The limit (one sentence)

A Hermes plugin can rewrite the LLM **request body** (via `llm_request` middleware) but **cannot
change which provider/account the turn is sent to** — the provider, transport, and credentials are
fixed before any plugin code runs and are not re-read from the body.

## Why (the evidence)

- `agent/conversation_loop.py:874–895` builds `api_kwargs` (the OpenAI/Responses request body), then
  calls `apply_llm_request_middleware(api_kwargs, ...)`. The middleware's returned `{"request": ...}`
  replaces the body. `model/provider/base_url/api_mode` are passed in as **read-only context**.
- After middleware returns, the request is sent through the transport already constructed for
  `agent.provider` / `agent.base_url` / `agent.api_key`. Nothing downstream re-resolves the provider
  from the (possibly changed) body.
- Plugin **hooks** (`pre_llm_call`, `pre_api_request`, …) fire **after** model selection, so they
  can't reroute a turn either.

**Net:** middleware can swap the `model` string **within the current provider**; it cannot send the
turn to a *different* provider that needs different auth (e.g. Kimi → Claude Opus → GPT-5.5).

## What this blocks from the original plan

| Original plan capability | Status with v0.1 (plugin only) |
| --- | --- |
| Per-turn **same-provider** model tiering (e.g. a light vs heavy model on one provider, or all tiers via OpenRouter) | ✅ Works — the middleware swaps the model. |
| Local, no-LLM-call **complexity classification** (the determination core) | ✅ Works fully — reusable, explainable, exposed for routing/logging. |
| **Transparent per-turn cross-provider routing** — type into your normal Kimi session and have a hard prompt silently answered by Opus 4.8 / GPT-5.5 | ❌ **Not possible via the plugin.** The middleware can't re-auth to another provider mid-turn. |
| "Hard tasks automatically land on Opus/GPT-5.5" on ordinary interactive turns | ❌ Not automatic across providers. ⚠️ Achievable by other means (below). |

**Concretely, the one thing we cannot do today:** with your multi-provider OAuth tiers
(`kimi-coding` / `openai-codex` / `anthropic`), the plugin will *detect* that a turn should go to a
different provider and **log it, but not reroute it** — `same_provider_only: true` keeps behaviour
correct rather than sending an Opus model name to Kimi's endpoint.

## What we *can* still do (workarounds)

1. **Manager / delegation path (config-only, works today, cross-provider OK).** Make GPT-5.5 the
   `delegation.model` and `auxiliary.kanban_decomposer`. Delegated/decomposed sub-tasks run as child
   agents, which *are* allowed a different provider — so cross-provider routing works at the delegation
   boundary (for goals that decompose, not every interactive turn).
2. **Capability-tier profiles (manual).** A "heavy" profile whose primary is Opus/GPT-5.5, launched
   deliberately for hard work (fits the multi-terminal workflow).
3. **Single-provider tiering.** If all tiers live under one provider (e.g. OpenRouter, or a local
   proxy), the middleware reroutes freely — at the cost of not using the per-provider OAuth logins.

## The clean fix (DRAFTED — see `upstream/`)

The fix is a small **upstream PR to `NousResearch/hermes-agent`** adding a `model_request`
(pre-model-selection) middleware seam **inside** `gateway/run.py:_resolve_turn_agent_config`, before
credentials are bound, so a plugin can pick the provider + model and Hermes re-resolves credentials via
`resolve_runtime_provider`. This turns transparent per-turn cross-provider routing from "impossible via
plugin" into a registered middleware — decided locally, at the gateway, with **no LLM call**.

It is drafted and verified in [`../upstream/`](../upstream/): the patch applies cleanly to
hermes-agent `main`, the seam round-trips a re-route in a functional check, and this plugin already
registers the matching `model_request` middleware (so cross-provider routing activates the moment a
Hermes build with the seam is in use). Until the PR merges, `same_provider_only` keeps stock behaviour
correct. See [`PLAN.md`](PLAN.md) Roadmap.
