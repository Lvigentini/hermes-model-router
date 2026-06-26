"""Map a determination Decision onto a concrete routing target.

Separated from both the heuristic (``determination.py``) and the Hermes wiring
(``middleware.py``) so the policy "tier → which provider/model" is one small,
testable place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .config import RouterConfig
from .determination import Decision
from .directives import detect_directive


def directive_route(
    text: str,
    cfg: RouterConfig,
    *,
    current_provider: str,
    current_model: str,
) -> Optional["RouteTarget"]:
    """Return a RouteTarget for an explicit in-message directive, or None.

    Highest priority: overrides the heuristic and any session pin. Confidence is
    1.0 (the user told us). Returns None when no directive is present or it asks
    for the model we're already on with no tier fallback to apply.
    """
    if not cfg.directives:
        return None
    d = detect_directive(text, cfg.resolved_aliases())
    if not d:
        return None
    provider, model = d["provider"], d["model"]
    cross_provider = provider != (current_provider or "")
    model_changed = model != current_model or cross_provider
    fallback = cfg.fallback_for_target(provider, model)
    if not model_changed and not fallback:
        return None
    return RouteTarget(
        provider=provider, model=model, tier="directive",
        confidence=1.0, reason=f"explicit directive: {d['phrase']}",
        cross_provider=cross_provider, fallback=fallback, model_changed=model_changed,
    )


@dataclass
class RouteTarget:
    provider: str
    model: str
    tier: str
    confidence: float
    reason: str
    cross_provider: bool  # target provider differs from the current turn's
    fallback: List[dict] = field(default_factory=list)  # per-tier fallback chain
    model_changed: bool = True  # False when only the fallback chain is being set


def resolve_route(
    decision: Decision,
    cfg: RouterConfig,
    *,
    current_provider: str,
    current_model: str,
    allow_cross_provider: bool = False,
) -> Optional[RouteTarget]:
    """Return the RouteTarget to apply, or None to leave the turn untouched.

    None is returned when: routing is disabled, the confidence gate isn't met,
    or the target equals the current model. A cross-provider hop is returned as
    a suppressed RouteTarget unless ``allow_cross_provider`` is True — the
    ``llm_request`` seam can't re-auth (so suppress), but the ``model_request``
    seam can (so allow). See docs/PLAN.md and docs/LIMITATIONS.md.
    """
    if not cfg.enabled:
        return None
    if decision.confidence < cfg.gate_confidence:
        return None

    target = cfg.target_for(decision.tier)
    provider, model = target.get("provider", ""), target.get("model", "")
    if not provider or not model:
        return None

    fallback = cfg.fallback_for(decision.tier)
    cross_provider = provider != (current_provider or "")
    model_changed = model != current_model or cross_provider

    # Already on the target model AND no tier fallback to apply → nothing to do.
    if not model_changed and not fallback:
        return None

    if cross_provider and not allow_cross_provider and cfg.same_provider_only:
        return RouteTarget(
            provider=provider, model=model, tier=decision.tier,
            confidence=decision.confidence,
            reason="cross-provider route suppressed (same_provider_only)",
            cross_provider=True, fallback=fallback, model_changed=model_changed,
        )

    return RouteTarget(
        provider=provider, model=model, tier=decision.tier,
        confidence=decision.confidence,
        reason=f"tier={decision.tier} conf={decision.confidence:.2f}",
        cross_provider=cross_provider, fallback=fallback, model_changed=model_changed,
    )
