# UX: showing the decision, letting the user override, and listing models

Answers to two questions: (1) how the end user sees and can reject a routing decision, and (2) how
Hermes enumerates the models you can route to.

## 1. Showing the model decision, and "user makes the call"

### Seeing which model answered
- **`/footer`** — toggles `display.runtime_footer` (fields default `[model, context_pct, cwd]`). With
  it on, every final reply shows the **model that produced it**, so a re-route is visible for free.
  Config: `display.runtime_footer.enabled: true`.
- **`hermes logs`** — the router emits a one-line decision per turn, e.g.
  `model_request: re-routed turn kimi-coding/kimi-for-coding -> anthropic/claude-opus-4-8` (auto) or
  `model-router[announce]: reasoning (conf 0.72) suggests anthropic/claude-opus-4-8` (announce).
- **Telemetry** — the decision rides in the `middleware_trace` passed to the `pre_api_request` hook
  (`source: hermes-model-router`, `reason: …`), so observability plugins can surface it.

### Letting the user make the call (the `mode` dial)
`model_router.mode` is the primary control:

| mode | behaviour |
| --- | --- |
| `auto` | classify and **switch** automatically (cross-provider on a patched build). |
| `announce` | classify and **show the suggestion** in logs, but **do not switch** — you keep your default model and decide. This is "router advises, user calls it." |
| `off` | do nothing — fully manual. |

Other levers:
- **`/model <name>`** pins a model for the session and the router **stands down** (with
  `respect_explicit_model: true`, the default) — your pin wins even in `auto` mode. The gateway tags a
  pinned turn as `explicit_model` and the `model_request` middleware returns "no change". Set
  `respect_explicit_model: false` to let the router override pins. (Pin-respect rides the upstream seam;
  on a stock/unpatched build the same-provider `llm_request` path can't see the pin, so use
  `mode: announce`/`off` there for strict manual control.)
- **`gate_confidence`** — raise it (e.g. `0.7`) so only clearly-hard prompts trigger a switch; ambiguous
  prompts stay on the default. Fewer surprises.
- **Per-tier defaults** — set the `cheap` tier to your everyday model so "no strong signal" always means
  "stay cheap."

### Roadmap for richer control
- A **`/route`** slash command: show the last decision, and `accept` / `pin` / `disable` it.
- **Interactive confirm** before a switch via Hermes' approvals system (`pre_approval_request`) — a
  per-turn "route this to Opus? [Y/n]" gate, opt-in via config (heavier; suited to high-stakes use).

## 2. How Hermes identifies available models

Hermes does **not** hardcode a fixed list — it discovers per provider:
- **Interactive:** `hermes model` → `select_provider_and_model()` presents provider + model choices.
- **Programmatic:** `hermes_cli.models.curated_models_for_provider(provider)` → `[(model_id, desc), …]`.
  It tries the provider's **live `/models` API** first (Codex, Nous, Anthropic, etc.), then falls back
  to a **static catalog** (`_PROVIDER_MODELS`). Results are cached in
  `$HERMES_HOME/provider_models_cache.json` (e.g. the `anthropic` entry lists `claude-opus-4-8`,
  `claude-sonnet-4-6`, …).
- **Catalog/pricing:** `hermes_cli.model_catalog` + `model_catalog.url` in config (a models.dev-style
  catalog) and `fetch_models_with_pricing(...)` add pricing/context metadata.

### Using that in this plugin
`hermes_model_router/models.py` wraps the above so you can populate and **validate** the tier map:
```bash
# list models Hermes can route to, per provider, and check the default tier map
python -m hermes_model_router.models                 # validates default tiers + lists tier providers
python -m hermes_model_router.models anthropic openai-codex kimi-coding
```
- `available_models(provider)` → ids Hermes knows for that provider (live → cache → []).
- `validate_tiers(cfg)` → warnings for any tier whose `model` isn't in its provider's catalog, so a
  typo'd tier target is caught before it silently fails at call time.
