"""Configuration schema + defaults for hermes-model-router.

Read from the Hermes config under the ``model_router:`` key (plugin config is
surfaced via the plugin context). Everything here is plain data so it can be
loaded without Hermes for tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

# Default tier → target. Reuses the user's already-authenticated Hermes
# providers (kimi/codex/claude OAuth) — no new credentials required.
DEFAULT_TIERS: Dict[str, Dict[str, str]] = {
    "cheap":     {"provider": "kimi-coding",  "model": "kimi-for-coding"},
    "smart":     {"provider": "openai-codex", "model": "gpt-5.5"},
    "reasoning": {"provider": "anthropic",    "model": "claude-opus-4-8"},
}

DEFAULTS: Dict[str, Any] = {
    "enabled": True,
    # Below this confidence, leave the turn on its current model (no-match gate).
    "gate_confidence": 0.55,
    # An explicit /model selection or per-message override always wins.
    "respect_explicit_model": True,
    # If a tier maps to a DIFFERENT provider than the current turn, the
    # llm_request middleware cannot re-auth (see docs/PLAN.md "Seam finding").
    # When true, only same-provider model swaps are applied; cross-provider
    # routing is logged but left to the manager/upstream-hook path.
    "same_provider_only": True,
    "tiers": DEFAULT_TIERS,
}


@dataclass
class RouterConfig:
    enabled: bool = True
    gate_confidence: float = 0.55
    respect_explicit_model: bool = True
    same_provider_only: bool = True
    tiers: Dict[str, Dict[str, str]] = field(default_factory=lambda: dict(DEFAULT_TIERS))

    @classmethod
    def from_mapping(cls, raw: Dict[str, Any] | None) -> "RouterConfig":
        raw = dict(DEFAULTS, **(raw or {}))
        tiers = {**DEFAULT_TIERS, **(raw.get("tiers") or {})}
        return cls(
            enabled=bool(raw.get("enabled", True)),
            gate_confidence=float(raw.get("gate_confidence", 0.55)),
            respect_explicit_model=bool(raw.get("respect_explicit_model", True)),
            same_provider_only=bool(raw.get("same_provider_only", True)),
            tiers=tiers,
        )

    def target_for(self, tier: str) -> Dict[str, str]:
        return self.tiers.get(tier, self.tiers["smart"])
