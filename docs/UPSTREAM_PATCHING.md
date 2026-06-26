# Upstream patch & PR guide (Nous `hermes-agent`)

How to (a) run a **locally patched** Hermes so cross-provider routing works today, and (b) open the
**official PR** later. The patch and PR body live in [`../upstream/`](../upstream/).

- Patch: `upstream/0001-add-pre-model-selection-seam.patch` (2 files, +118/−6)
- PR description: `upstream/README.md`
- Target: `NousResearch/hermes-agent` `main` (authored against `8cf9d86`)
- What it adds: a `model_request` (pre-model-selection) middleware seam in
  `gateway/run.py:_resolve_turn_agent_config`, fired before credentials are bound, so a plugin can
  re-route a turn to a different **model and provider**. Hermes re-resolves credentials for the chosen
  provider via the existing `resolve_runtime_provider`. Fail-open; zero-overhead when unused.

---

## A. Run a locally patched Hermes (to test now)

Hermes lives at `~/.hermes/hermes-agent` (a git checkout of `main`).

```bash
cd ~/.hermes/hermes-agent
git stash -u                                   # park the node_modules churn, if any
cp -r . /tmp/hermes-agent.bak                  # optional full backup
git apply --check ~/_coding/hermes-model-router/upstream/0001-add-pre-model-selection-seam.patch  # dry run
git apply        ~/_coding/hermes-model-router/upstream/0001-add-pre-model-selection-seam.patch
python -m py_compile hermes_cli/middleware.py gateway/run.py   # sanity
```

Restart the gateway / TUI so the new code loads. **Revert** any time with:

```bash
cd ~/.hermes/hermes-agent
git apply -R ~/_coding/hermes-model-router/upstream/0001-add-pre-model-selection-seam.patch
# or, nuke local changes entirely:
git checkout -- hermes_cli/middleware.py gateway/run.py
```

### Surviving `hermes update`
`hermes update` does `git pull` on `main` (stashing local changes first). The patch is **not**
committed, so an update can drop or conflict with it. After any update, re-apply:

```bash
cd ~/.hermes/hermes-agent && git apply ~/_coding/hermes-model-router/upstream/0001-add-pre-model-selection-seam.patch
```

If `git apply` fails after an upstream change to those two files, regenerate the patch against the new
`main` (see "Maintaining the patch" below). The cleanest long-term answer is to **land the PR** so the
seam ships in `main` and no local patching is needed.

### Tip: keep a dedicated patched checkout
To avoid fighting `hermes update`, clone a second copy for experimentation and point a profile at it,
rather than patching the auto-updating install:
```bash
git clone https://github.com/NousResearch/hermes-agent /tmp/hermes-patched
cd /tmp/hermes-patched && git apply ~/_coding/hermes-model-router/upstream/0001-add-pre-model-selection-seam.patch
```

---

## B. Open the official PR

```bash
# 1. Fork NousResearch/hermes-agent on GitHub (gh repo fork NousResearch/hermes-agent --clone)
git clone https://github.com/<you>/hermes-agent && cd hermes-agent
git checkout -b feat/pre-model-selection
git apply ~/_coding/hermes-model-router/upstream/0001-add-pre-model-selection-seam.patch
git add hermes_cli/middleware.py gateway/run.py
git commit -m "feat(gateway): pre-model-selection middleware seam for per-turn cross-provider routing"
git push -u origin feat/pre-model-selection
# 2. Open the PR; paste upstream/README.md as the description.
```

Before pushing, run the repo's own checks (`pytest -q` on the touched areas, e.g.
`tests/hermes_cli/test_plugins.py`) and follow `CONTRIBUTING.md`.

### Maintaining the patch (if `main` drifts)
1. Apply the current patch to a fresh `main` checkout; if it fails, apply the two hunks by hand
   (`hermes_cli/middleware.py` adds `MODEL_REQUEST_MIDDLEWARE` + `apply_model_request_middleware`;
   `gateway/run.py` adds `_apply_model_selection` and one call inside `_resolve_turn_agent_config`).
2. Regenerate: `git diff main -- hermes_cli/middleware.py gateway/run.py > 0001-add-pre-model-selection-seam.patch`
3. Commit the refreshed patch to this repo (the pre-commit hook bumps the version).

---

## C. Verify the seam works (patched build)
```bash
# from the patched hermes-agent root
python - <<'PY'
import hermes_cli.plugins as P
from hermes_cli.middleware import apply_model_request_middleware, MODEL_REQUEST_MIDDLEWARE, VALID_MIDDLEWARE
assert MODEL_REQUEST_MIDDLEWARE in VALID_MIDDLEWARE
P.get_plugin_manager()._middleware.setdefault(MODEL_REQUEST_MIDDLEWARE, []).append(
    lambda request=None, user_message="", **k:
        {"request": {**request, "model": "claude-opus-4-8", "provider": "anthropic"}}
        if "prove" in user_message.lower() else None)
r = apply_model_request_middleware({"model":"kimi-for-coding","provider":"kimi-coding"}, user_message="prove it")
print("re-routed to", r.payload["provider"], r.payload["model"], "| changed", r.changed)
PY
```
Expected: `re-routed to anthropic claude-opus-4-8 | changed True`.

Then install the plugin (see repo README), set `model_router.mode: auto`, and confirm a hard prompt
binds to the reasoning-tier model (watch `hermes logs` for `model_request: re-routed …`).
