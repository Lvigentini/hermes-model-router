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
    # User-control dial:
    #   "auto"     — classify and switch the model automatically.
    #   "announce" — classify and LOG the suggestion, but DO NOT switch (the user
    #                keeps their default model; they "make the call"). Pair with
    #                `/footer` to see the active model.
    #   "off"      — do nothing (fully manual).
    "mode": "auto",
    # Below this confidence, leave the turn on its current model (no-match gate).
    "gate_confidence": 0.55,
    # An explicit /model selection or per-message override always wins.
    "respect_explicit_model": True,
    # If a tier maps to a DIFFERENT provider than the current turn, the
    # llm_request middleware cannot re-auth (see docs/PLAN.md "Seam finding").
    # When true, only same-provider model swaps are applied; cross-provider
    # routing is logged but left to the manager/upstream-hook path.
    "same_provider_only": True,
    # Honour an explicit in-message model directive ("use opus to …"), which
    # overrides the heuristic and any session pin for that turn.
    "directives": True,
    # Extra name → {provider, model} aliases for directives. Merged on top of the
    # built-ins and the configured tier names.
    "aliases": {},
    "tiers": DEFAULT_TIERS,
}


@dataclass
class RouterConfig:
    enabled: bool = True
    mode: str = "auto"            # auto | announce | off
    gate_confidence: float = 0.55
    respect_explicit_model: bool = True
    same_provider_only: bool = True
    directives: bool = True
    aliases: Dict[str, Dict[str, str]] = field(default_factory=dict)
    tiers: Dict[str, Dict[str, str]] = field(default_factory=lambda: dict(DEFAULT_TIERS))

    @classmethod
    def from_mapping(cls, raw: Dict[str, Any] | None) -> "RouterConfig":
        raw = dict(DEFAULTS, **(raw or {}))
        tiers = {**DEFAULT_TIERS, **(raw.get("tiers") or {})}
        mode = str(raw.get("mode", "auto")).lower()
        if mode not in ("auto", "announce", "off"):
            mode = "auto"
        return cls(
            enabled=bool(raw.get("enabled", True)),
            mode=mode,
            gate_confidence=float(raw.get("gate_confidence", 0.55)),
            respect_explicit_model=bool(raw.get("respect_explicit_model", True)),
            same_provider_only=bool(raw.get("same_provider_only", True)),
            directives=bool(raw.get("directives", True)),
            aliases=dict(raw.get("aliases") or {}),
            tiers=tiers,
        )

    def resolved_aliases(self) -> Dict[str, Dict[str, str]]:
        """Built-in nicknames + configured tier names/models + user aliases."""
        from .directives import BUILTIN_ALIASES
        out: Dict[str, Dict[str, str]] = dict(BUILTIN_ALIASES)
        for tier, tgt in self.tiers.items():
            provider, model = tgt.get("provider"), tgt.get("model")
            if provider and model:
                entry = {"provider": provider, "model": model}
                out[tier.lower()] = entry           # "cheap" / "smart" / "reasoning"
                out[str(model).lower()] = entry     # the exact model id
        out.update(self.aliases or {})              # user overrides win
        return out

    def fallback_for_target(self, provider: str, model: str) -> list:
        """Return the per-tier fallback for whichever tier matches (provider, model)."""
        for tier, tgt in self.tiers.items():
            if tgt.get("provider") == provider and tgt.get("model") == model:
                return self.fallback_for(tier)
        return []

    @property
    def active(self) -> bool:
        """True when the router should actually switch models."""
        return self.enabled and self.mode == "auto"

    @property
    def observing(self) -> bool:
        """True when the router should classify (to switch or just announce)."""
        return self.enabled and self.mode in ("auto", "announce")

    def target_for(self, tier: str) -> Dict[str, str]:
        return self.tiers.get(tier, self.tiers["smart"])

    def fallback_for(self, tier: str) -> list:
        """Per-tier fallback chain (ordered ``[{provider, model}, ...]``).

        Opt-in: a tier with no ``fallback`` key returns ``[]`` and the turn keeps
        the global ``fallback_providers`` chain. When present, this REPLACES the
        global chain for that turn so a cheap turn that fails retries on another
        cheap model instead of escalating up the global chain.
        """
        raw = (self.target_for(tier) or {}).get("fallback") or []
        chain = []
        for e in raw:
            if isinstance(e, dict) and e.get("provider") and e.get("model"):
                entry = {"provider": str(e["provider"]), "model": str(e["model"])}
                if e.get("base_url"):
                    entry["base_url"] = str(e["base_url"])
                chain.append(entry)
        return chain
