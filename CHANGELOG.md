# Changelog

Versioning is **semver `x.y.z`**. The **patch** number is bumped automatically on
every commit by the pre-commit hook (`.githooks/pre-commit` → `scripts/bump_version.py`).
Bump minor/major manually with `python3 scripts/bump_version.py minor|major` when a
commit warrants it.

## 0.1.x
- Initial scaffold: local heuristic determination core (`classify`), tier→target
  map, and `llm_request` middleware (same-provider model swap).
- Verified Hermes seam limit (cross-provider routing not possible via middleware);
  documented in `docs/LIMITATIONS.md`.
- Added `model_request` middleware (cross-provider live routing) + drafted the
  upstream `pre_model_selection` seam patch in `upstream/` (applies cleanly to
  hermes-agent `main`, functionally verified). Activates when a Hermes build with
  the seam is in use; no-op on stock builds.
