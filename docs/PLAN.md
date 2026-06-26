# hermes-model-router — Design & Plan

## Why this exists

[Hermes](https://github.com/NousResearch/hermes-agent) (Nous Research) runs every turn on one
configured model, with a *failure-driven* fallback chain. There is no **complexity-driven** routing:
a hard prompt that the cheap primary handles *badly* never escalates, and an easy prompt still pays
for a strong model only if you set the primary high.

This plugin adds a **local, no-LLM-call complexity router**: classify each turn into a tier
(`cheap` / `smart` / `reasoning`) and route to a tier-appropriate model. It pairs with a config-only
**goal manager** (GPT-5.5 as Hermes' kanban/delegation orchestrator) so multi-step goals decompose
and each sub-task is tier-routed by the same core.

Design goal the project most cares about: **determine complexity locally, deterministically, with no
LLM call.** That is achievable (this is ClawRouter / RouteLLM territory) and is the heart of the repo.

## Research summary (what informed the design)

- **OpenClaw is the open-source lineage Hermes descends from.** Its routing splits into three patterns:
  *ClawRouter* (per-request classify→tier→cheapest-capable model, rule-based, <1ms),
  *openclaw-orchestrator* (a toolless LLM planner that decomposes a goal and routes sub-tasks to
  specialist agents — "orchestrator coordinates, agents execute"), and *bindings* (static channel→agent
  rules, each agent its own model = Hermes profiles).
- **"Local, no-LLM-call routing" is standard.** Spectrum: heuristic scorer (zero ML, sub-ms) →
  embedding/semantic router → tiny trained classifier (RouteLLM BERT/matrix-factorisation, ~85% cost
  cut at ~95% GPT-4 quality, still local). We start heuristic; the interface allows a drop-in upgrade.
- **OpenRouter "Fusion" is NOT a cost router** — it is multi-model deliberation (panel + judge +
  synthesis), i.e. the Mixture-of-Agents pattern Hermes already ships. Out of scope here.
- **`eagle-eye`** (a Hermes plugin) is the closest in-ecosystem template: 5-layer *local* skill routing
  (hard triggers → BM25 → synonyms → embeddings → RRF) on a `pre_llm_call` hook. We mirror its shape
  for *model* selection.

Sources: ClawRouter `github.com/BlockRunAI/ClawRouter`; openclaw-orchestrator
`github.com/zeynepyorulmaz/openclaw-orchestrator`; OpenClaw multi-agent `docs.openclaw.ai/concepts/multi-agent`;
RouteLLM `github.com/lm-sys/RouteLLM`; OpenRouter Fusion `openrouter.ai/docs/guides/routing/routers/fusion-router`.

## Seam finding (verified against Hermes source) — important

Hermes plugin **hooks fire *after* the per-turn model is chosen**, so they cannot reroute a turn.
Plugins *can* register **`llm_request` middleware** (`hermes_cli/middleware.py`,
`agent/conversation_loop.py:874–895`) that rewrites the request body before the call. **But** the
turn's provider/transport/credentials are already constructed before middleware runs and are not
re-read from the body. Therefore:

- ✅ `llm_request` middleware can swap the **model within the current provider** (safe — applied here).
- ❌ It **cannot** redirect to a **different provider** with different credentials (kimi → opus).

This is why cross-provider routing is **suppressed by default** (`same_provider_only: true`) and left
to the manager/delegation path. The clean long-term fix is a small upstream PR to Hermes adding a
**`pre_model_selection` hook** (fires before `gateway/run.py:_resolve_turn_agent_config`), which would
let the same determination core drive true cross-provider per-turn routing. See Roadmap.

## Architecture (three decoupled units)

1. **`determination.py` — the core.** `classify(text, ctx) -> Decision{tier, confidence, est_tokens,
   scores}`. Pure, local, no API, no Hermes dependency → unit-testable in isolation. v1 is a transparent
   weighted heuristic over signals (length, code, reasoning markers, multi-step, technical vocab,
   task verbs, simple-intent). `scores` makes every decision explainable for tuning.
2. **`config.py` + `tiers.py` — policy.** `tier → {provider, model}` map (default reuses the user's
   existing Hermes OAuth logins: kimi / openai-codex / anthropic). `resolve_route` applies the
   confidence gate, the explicit-override rule, the no-op check, and the same-provider guard.
3. **`middleware.py` + `__init__.py` — the Hermes wiring.** An `llm_request` middleware that reads the
   latest user turn, classifies, and (same-provider) rewrites `model`. Cross-provider routes are traced,
   not applied. Fail-safe: any error returns "no change" so the agent loop never breaks.

**Goal manager (config-only, no code in this repo):**
```yaml
auxiliary: { kanban_decomposer: { provider: openai-codex, model: gpt-5.5 } }
delegation: { model: gpt-5.5, provider: openai-codex, orchestrator_enabled: true }
```

## Configuration (`model_router:` in Hermes config.yaml)
```yaml
model_router:
  enabled: true
  gate_confidence: 0.55          # below this, leave the turn on its current model
  respect_explicit_model: true   # /model and per-message overrides win
  same_provider_only: true       # see "Seam finding"
  tiers:
    cheap:     { provider: kimi-coding,  model: kimi-for-coding }
    smart:     { provider: openai-codex, model: gpt-5.5 }
    reasoning: { provider: anthropic,    model: claude-opus-4-8 }
```

## Status
- ✅ Determination core + tier policy + `llm_request` middleware implemented.
- ✅ 36 unit tests pass; eval set (`eval/prompts.jsonl`) tier-accuracy 100% (gate ≥85% for regressions).
- ⏳ Live install verification in Hermes (`~/.hermes/plugins/`) — same-provider swap end-to-end.
- ⏳ Cross-provider story: validate manager/delegation path; decide on the upstream `pre_model_selection` PR.

## Build split
- **Claude Code (scaffold, done here):** the three units, tests, eval harness, packaging, CI, docs.
- **Hermes `coder` agent (iterate):** tune weights/thresholds/vocab in `determination.py` against
  `eval/prompts.jsonl`; grow the tier map; optionally add the v2 classifier behind `classify()`.

## Roadmap
- **v0.1** heuristic core + same-provider middleware router + config-only manager.
- **v0.2** ← here. Upstream `model_request` (pre-model-selection) seam **drafted** in
  [`../upstream/`](../upstream/) (patch applies cleanly to hermes-agent `main`; functionally verified).
  Plugin registers a `model_request` middleware → **true cross-provider per-turn routing**, decided
  locally at the gateway with no LLM call. Lands once the upstream PR merges.
- **v0.3** optional local classifier (RouteLLM / ModernBERT) behind the `classify()` signature;
  per-signal weight learning from `eval/prompts.jsonl`.
- **out of scope (YAGNI):** cross-profile binding router, Fusion/MoA auto-invoke, cost dashboards.

## Verification
1. `pytest -q` — core + routing + eval accuracy gate.
2. Install to `~/.hermes/plugins/hermes-model-router/`, enable in `plugins.enabled`, set `model_router:`;
   run `hermes -z "<simple>"` vs `hermes -z "<hard>"` and confirm the chosen model in `hermes logs`.
3. Explicit `/model` override bypasses the router.
4. Multi-step goal: GPT-5.5 decomposes (kanban) and sub-tasks route per tier.
