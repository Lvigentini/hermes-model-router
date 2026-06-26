# AGENTS.md — maintenance handover for `hermes-model-router`

You (a Hermes coding agent) are taking over maintenance of this plugin. This file is your operating
brief. Read it fully before editing. Deep-dives live in `docs/` — don't duplicate them, follow them.

## Mission
A **local, no-LLM-call** complexity router for Hermes: classify each turn (`cheap`/`smart`/`reasoning`)
with a transparent heuristic and route to a tier-appropriate model — cheap work on cheap models, hard
work on strong ones (gpt-5.5 / claude-opus-4-8). Your job is to **tune and extend** it without breaking
its contracts. The hard engineering (the Hermes seam) is done; most of your work is heuristics, tiers,
and eval coverage.

## Where things live
- **Repo:** this directory (`~/_coding/hermes-model-router`). Remote: `github.com/Lvigentini/hermes-model-router`, branch `main`.
- **The loadable plugin is the `hermes_model_router/` package dir** (it holds `plugin.yaml` + `__init__.py` + the modules). It is symlinked into each Hermes profile that uses it:
  `~/.hermes/plugins/hermes-model-router` and `~/.hermes/profiles/<name>/plugins/hermes-model-router` → `…/hermes_model_router`. **Plugins are per-profile** (per `HERMES_HOME`) — installing in one profile does not cover another.
- **Editing the code here updates the live plugin** (the symlink points at this repo). Changes load on the **next Hermes start** — plugins register once at startup, so **restart the session/process** to pick up code or config changes.

## Architecture (modules + responsibilities)
| File | Responsibility | You'll edit this when… |
| --- | --- | --- |
| `hermes_model_router/determination.py` | `classify(text, ctx) -> Decision`. Pure, local, no API. `WEIGHTS`, `THRESHOLDS`, and the vocab lists (`_REASONING_MARKERS`, `_TASK_VERBS`, `_TECHNICAL_TERMS`, `_SIMPLE_INDICATORS`, `_CODE_PATTERNS`). | **Tuning routing accuracy** (most common task). |
| `hermes_model_router/config.py` | `RouterConfig`, `DEFAULT_TIERS`, `mode`/`gate_confidence`/`respect_explicit_model`/`same_provider_only`, `target_for`, `fallback_for`. | Adding config knobs or defaults. |
| `hermes_model_router/tiers.py` | `resolve_route()` + `RouteTarget` (carries `fallback`, `model_changed`, `cross_provider`). Tier→model policy + gate. | Changing routing policy. |
| `hermes_model_router/middleware.py` | `make_llm_request_middleware` (same-provider swap + `announce`), `make_model_request_middleware` (cross-provider + emits per-tier `fallback`), `_latest_user_text`. | Changing how decisions are applied. |
| `hermes_model_router/models.py` | `available_models(provider)`, `validate_tiers(cfg)`, CLI. Uses Hermes' `curated_models_for_provider`. | Validating tier models exist. |
| `hermes_model_router/__init__.py` | `register(ctx)` — reads `model_router:` config via `hermes_cli.config`, registers both middlewares. `__version__`. | Rarely. |
| `upstream/` | The `model_request` seam patch for `NousResearch/hermes-agent` + PR text. | Maintaining the patch (see below). |

**Invariant:** keep `classify(text, ctx) -> Decision` signature stable. A future v2 (RouteLLM/ModernBERT)
must drop in behind it without touching `tiers.py`/`middleware.py`.

## The Hermes seam (read `docs/LIMITATIONS.md` + `docs/UPSTREAM_PATCHING.md`)
Cross-provider routing needs an **upstream patch** (`upstream/0001-add-pre-model-selection-seam.patch`),
applied to the local editable install at `~/.hermes/hermes-agent`. It adds a `model_request` seam at
**two** points: the gateway (`_resolve_turn_agent_config`) and the in-process path
(`conversation_loop.run_conversation`, via `agent.switch_model`). On stock Hermes the plugin still loads
but only does same-provider swaps. **Tier-aware fallback is applied on the in-process path only** today
(the gateway uses the global chain — a known follow-up).
**After every `hermes update`, re-apply the patch** (or the seam disappears): see `docs/UPSTREAM_PATCHING.md`.

## Dev loop (run from the repo root)
```bash
.venv/bin/pip install -e ".[dev]"          # one-time; .venv already exists
PYTHONPATH=. .venv/bin/python -m pytest -q  # 46 tests must stay green
python -m hermes_model_router.models        # validate the default tier map + list provider models
```
**Versioning is automatic:** a pre-commit hook (`.githooks/pre-commit`, `core.hooksPath=.githooks`) bumps
the **patch** version on every commit and syncs `VERSION`/`pyproject.toml`/`plugin.yaml`/`__init__.py`.
For a feature/breaking change run `python3 scripts/bump_version.py minor|major` before committing.

## Maintenance recipes
1. **Tune routing** (the main task): edit `WEIGHTS`/`THRESHOLDS`/vocab in `determination.py`. Add labelled
   cases to `eval/prompts.jsonl` first (TDD). Run pytest — `test_eval_accuracy_threshold` enforces
   **≥85% tier accuracy**; keep it passing. Each signal in `Decision.scores` is explainable — use it to
   debug why a prompt landed in a tier.
2. **Change tiers / per-tier fallback:** edit the user's `model_router.tiers` in the relevant profile
   config (`~/.hermes/profiles/<name>/config.yaml`), or `DEFAULT_TIERS` in `config.py`. Each tier may
   carry a `fallback: [{provider, model}, …]` that replaces the global chain for that tier (keeps a cheap
   turn cheap on failure). Validate models exist: `python -m hermes_model_router.models <provider>`.
3. **Maintain the upstream patch** after Hermes updates: see `docs/UPSTREAM_PATCHING.md` →
   "Maintaining the patch". Regenerate with `git -C ~/.hermes/hermes-agent diff main -- <4 files>` and
   commit the refreshed `upstream/0001-*.patch`.
4. **v2 classifier** (optional, `docs/PLAN.md` roadmap): implement a local embedding/ModernBERT/RouteLLM
   classifier behind `classify()` — no downstream changes.
5. **Gateway tier-fallback** (follow-up): thread the `model_request` result's `fallback` into the gateway
   agent build (`gateway/run.py`). Currently in-process only.

## Testing it live (important nuances)
- Fresh-process test (each run = "restarted"):
  `HERMES_HOME=~/.hermes/profiles/coder ~/.local/bin/hermes -z "<prompt>"`.
- **Routing logs are suppressed in quiet/oneshot mode** — silence is NOT failure. In the interactive TUI,
  use the **footer** (`/footer`, already on) to see which model answered. To assert routing in a script,
  temporarily write the post-route `agent.model` to a file at the seam (see git history for the marker
  technique) and remove it after.
- A clean check with no LLM call: register the real middleware and call `_maybe_route_turn` on a fake
  agent (see `tests/` + the harnesses in git history).
- **Restart** the Hermes session after any code/config change.

## Guardrails (do not violate)
- **Fail-open:** routing must never break a turn. Keep the `try/except` in middlewares and `_maybe_route_turn`.
- **No LLM calls in the decision path.** The point is local, sub-ms classification.
- **Keep tests green and eval ≥85%** before committing. The commit hook bumps the version — don't fight it.
- **No secrets** in the repo. Tier configs reference provider/model names only; credentials stay in Hermes.
- **Respect pins:** `respect_explicit_model` must keep working (a user `/model` stands the router down).
- Don't edit `~/.hermes/hermes-agent` source except to (re)apply the `upstream/` patch.

## Definition of done for a change
1. `PYTHONPATH=. .venv/bin/python -m pytest -q` green (incl. eval threshold).
2. New behaviour covered by a test and/or an `eval/prompts.jsonl` case.
3. If tiers changed: `python -m hermes_model_router.models` shows no "not in catalog" warnings.
4. Live smoke on the coder profile (cheap stays cheap, hard routes up).
5. Commit (version auto-bumps) and push.

Further reading: `docs/PLAN.md` (design), `docs/UI.md` (modes, pins, model enumeration),
`docs/LIMITATIONS.md` (seam), `docs/UPSTREAM_PATCHING.md` (the patch), `README.md` (user-facing).
