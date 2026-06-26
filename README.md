# hermes-model-router

Local, **no-LLM-call** complexity router for the [Hermes agent](https://github.com/NousResearch/hermes-agent)
(Nous Research). It classifies each turn into a tier — `cheap` / `smart` / `reasoning` — with a
transparent weighted heuristic (sub-millisecond, zero ML, zero network) and routes to a
tier-appropriate model, so easy prompts run cheap and hard prompts get a strong model.

> Full design and research: [`docs/PLAN.md`](docs/PLAN.md). What this router **can't** do today and why
> (the verified Hermes seam limit): [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md).

## How it works

```
prompt ─► determination.classify()  ─►  tier + confidence + explainable scores
                                          │   (local · deterministic · no API)
                                          ▼
                     config tiers:  cheap / smart / reasoning  ─►  {provider, model}
                                          ▼
            llm_request middleware:  swap model (same-provider) before the call
```

- **`cheap`** — short factual / transform / simple tasks → e.g. `kimi-for-coding`
- **`smart`** — coding, SQL, explanations, comparisons → e.g. `gpt-5.5`
- **`reasoning`** — proofs, architecture, deep debugging, trade-off analysis → e.g. `claude-opus-4-8`

## Install (local)

The loadable plugin **is the `hermes_model_router/` package dir** (it holds `plugin.yaml` +
`__init__.py`). Symlink that dir into your Hermes plugins folder:

```bash
git clone <your-remote> ~/_coding/hermes-model-router
ln -s ~/_coding/hermes-model-router/hermes_model_router ~/.hermes/plugins/hermes-model-router
```

Enable it and configure tiers in your Hermes `config.yaml`:

```yaml
plugins:
  enabled: [hermes-model-router]

model_router:
  enabled: true
  mode: auto                     # auto | announce (show, don't switch) | off
  gate_confidence: 0.55          # below this confidence, leave the model unchanged
  respect_explicit_model: true   # an explicit /model selection should win (see docs/UI.md)
  same_provider_only: true       # see docs/LIMITATIONS.md "Seam finding"
  tiers:
    cheap:     { provider: kimi-coding,  model: kimi-for-coding }
    smart:     { provider: openai-codex, model: gpt-5.5 }
    reasoning: { provider: anthropic,    model: claude-opus-4-8 }
```

### Tier-aware fallback (optional)

By default a routed turn that fails (out of credits / rate-limit) falls back down Hermes' **global**
`fallback_providers` chain — which can escalate a *cheap* turn up to Opus. Give a tier its own
`fallback` list and that list **replaces** the global chain for that turn, so a cheap turn stays cheap:

```yaml
model_router:
  tiers:
    cheap:
      provider: kimi-coding
      model: kimi-for-coding
      fallback:                       # cheap-tier turn fails → try other CHEAP models, not Opus
        - { provider: kimi-coding, model: kimi-k2.6 }
        - { provider: google-gemini-cli, model: gemini-3.5-flash }
    reasoning:
      provider: anthropic
      model: claude-opus-4-8
      fallback:
        - { provider: openai-codex, model: gpt-5.5 }
        - { provider: google-gemini-cli, model: gemini-3-pro }
```

A tier with no `fallback` key keeps the global chain. Applied on the **in-process** path (TUI/CLI/
oneshot) via the seam; the gateway path currently uses the global chain (tier-fallback there is a
follow-up). `switch_model` preserves the chain, so failures still fall back correctly.

## Modes — and is "auto" a Hermes feature?

**No.** `mode` (and the whole notion of complexity-based routing) is **this plugin's**, not native
Hermes. Stock Hermes runs every turn on one configured model and only changes it on *failure* (the
`fallback_providers` chain) or a manual `/model`. There is no built-in "pick the model by how hard the
prompt is" — that gap is exactly why this plugin (and the upstream `model_request` seam in
[`docs/UPSTREAM_PATCHING.md`](docs/UPSTREAM_PATCHING.md)) exist.

| `model_router.mode` | what happens |
| --- | --- |
| `auto` | Each turn is classified locally (no LLM call) and the model is **switched** to the tier target. Cross-provider switching needs the `model_request` seam (patched/merged Hermes); same-provider works on stock. This is the "live switching" behaviour. |
| `announce` | Same classification, but it only **logs the suggestion** — your default model still answers. You decide whether to act (e.g. `/model …`). |
| `off` | Disabled. |

In `auto`, the flow per turn is: *user message → local heuristic → tier → `{provider, model}` → (gateway
binds credentials for that provider) → the turn runs on the chosen model.* The footer shows which model
answered; `hermes logs` shows the decision and reason.

## Pinning a model (you override the router)

Run **`/model <name>`** to pin a model for the session. With `respect_explicit_model: true` (default),
the router detects the pin and **stands down** — your pinned model is used as-is, even in `auto` mode.
Set `respect_explicit_model: false` if you want the router to override pins too.

How it works: a pin is a Hermes *session model override*; the gateway tags that turn as
`explicit_model` and passes it to the router's `model_request` middleware, which returns "no change"
when a pin is active. (This relies on the upstream seam; the tag is part of the patch in `upstream/`.)
On **stock** Hermes the same-provider `llm_request` path can't see the pin, so for strict manual
control on an unpatched build use `mode: announce` or `off`.

- **Showing/overriding the decision, and listing available models:** [`docs/UI.md`](docs/UI.md).
- **Live cross-provider routing (patch a local Hermes / open the PR):** [`docs/UPSTREAM_PATCHING.md`](docs/UPSTREAM_PATCHING.md).
- Validate your tier models exist: `python -m hermes_model_router.models`.

> **Cross-provider note:** Hermes' `llm_request` middleware can only swap the model *within the current
> provider*; it can't re-authenticate to a different provider mid-turn. So with `same_provider_only:
> true` (default), cross-provider routes are logged but not applied — use the goal-manager/delegation
> path for those, or track the upstream `pre_model_selection` hook (see `docs/PLAN.md`).

## Develop

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

The heuristic is tuned against [`eval/prompts.jsonl`](eval/prompts.jsonl) (labelled prompts). Edit the
weights/vocab in [`hermes_model_router/determination.py`](hermes_model_router/determination.py) and keep
tier accuracy ≥ 85%. The `classify()` signature is stable, so a future local classifier
(RouteLLM / ModernBERT) can drop in without touching the routing layers.

## License

MIT — see [LICENSE](LICENSE).
