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

```bash
git clone <your-remote> ~/_coding/hermes-model-router
ln -s ~/_coding/hermes-model-router ~/.hermes/plugins/hermes-model-router
```

Enable it and configure tiers in your Hermes `config.yaml`:

```yaml
plugins:
  enabled: [hermes-model-router]

model_router:
  enabled: true
  gate_confidence: 0.55          # below this confidence, leave the model unchanged
  respect_explicit_model: true   # an explicit /model selection always wins
  same_provider_only: true       # see docs/PLAN.md "Seam finding"
  tiers:
    cheap:     { provider: kimi-coding,  model: kimi-for-coding }
    smart:     { provider: openai-codex, model: gpt-5.5 }
    reasoning: { provider: anthropic,    model: claude-opus-4-8 }
```

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
