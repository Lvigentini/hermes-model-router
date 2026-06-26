"""Discover which models Hermes can choose from, and validate the tier map.

Answers "how does Hermes know what models exist?" in code: it asks the provider's
``/models`` API (cached) and falls back to a static catalog. We reuse that here so
the tier map can be populated and validated against models that actually exist.

Resolution order (each step is best-effort, never raises):
  1. ``hermes_cli.models.curated_models_for_provider`` — live API + catalog (best).
  2. ``$HERMES_HOME/provider_models_cache.json`` — the on-disk cache Hermes writes.
  3. ``[]`` — unknown (skip validation rather than block).
"""

from __future__ import annotations

import json
import os
import pathlib
from typing import Dict, List

from .config import RouterConfig


def _from_hermes(provider: str) -> List[str]:
    try:
        from hermes_cli.models import curated_models_for_provider
        return [m for (m, _desc) in curated_models_for_provider(provider)]
    except Exception:
        return []


def _from_cache(provider: str) -> List[str]:
    try:
        home = os.environ.get("HERMES_HOME") or str(pathlib.Path.home() / ".hermes")
        cache = json.loads((pathlib.Path(home) / "provider_models_cache.json").read_text())
        entry = cache.get(provider) or {}
        models = entry.get("models")
        return list(models) if isinstance(models, list) else []
    except Exception:
        return []


def available_models(provider: str) -> List[str]:
    """Return the model ids Hermes can route to for ``provider`` (best-effort)."""
    return _from_hermes(provider) or _from_cache(provider)


def validate_tiers(cfg: RouterConfig) -> List[str]:
    """Return human-readable warnings for tier targets that look unavailable.

    Empty list = everything checks out (or we couldn't enumerate, in which case
    we don't warn — absence of catalog data is not proof of a bad model).
    """
    warnings: List[str] = []
    by_provider: Dict[str, List[str]] = {}
    for tier, target in cfg.tiers.items():
        provider = target.get("provider", "")
        model = target.get("model", "")
        if not provider or not model:
            warnings.append(f"tier '{tier}': missing provider/model")
            continue
        known = by_provider.setdefault(provider, available_models(provider))
        if known and model not in known:
            warnings.append(
                f"tier '{tier}': model '{model}' not in {provider} catalog "
                f"({len(known)} known; e.g. {', '.join(known[:3])})"
            )
    return warnings


def _main() -> None:  # `python -m hermes_model_router.models [provider ...]`
    import sys

    providers = sys.argv[1:]
    if not providers:
        cfg = RouterConfig.from_mapping(None)
        providers = sorted({t["provider"] for t in cfg.tiers.values()})
        print("Validating default tier map:")
        for w in validate_tiers(cfg) or ["  all tier models look available"]:
            print(f"  - {w}")
        print()
    for p in providers:
        models = available_models(p)
        print(f"{p}: {len(models)} models")
        for m in models[:40]:
            print(f"  {m}")


if __name__ == "__main__":
    _main()
