"""Map a determination Decision onto a concrete routing target.

Separated from both the heuristic (``determination.py``) and the Hermes wiring
(``middleware.py``) so the policy "tier → which provider/model" is one small,
testable place.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from .config import RouterConfig
from .determination import Decision


@dataclass
class RouteTarget:
    provider: str
    model: str
    tier: str
    confidence: float
    reason: str
    cross_provider: bool  # target provider differs from the current turn's


def resolve_route(
    decision: Decision,
    cfg: RouterConfig,
    *,
    current_provider: str,
    current_model: str,
) -> Optional[RouteTarget]:
    """Return the RouteTarget to apply, or None to leave the turn untouched.

    None is returned when: routing is disabled, the confidence gate isn't met,
    the target equals the current model, or a cross-provider hop is required but
    ``same_provider_only`` forbids it (the middleware can't re-auth — see
    docs/PLAN.md).
    """
    if not cfg.enabled:
        return None
    if decision.confidence < cfg.gate_confidence:
        return None

    target = cfg.target_for(decision.tier)
    provider, model = target.get("provider", ""), target.get("model", "")
    if not provider or not model:
        return None

    cross_provider = provider != (current_provider or "")
    if model == current_model and not cross_provider:
        return None  # already where we want to be
    if cross_provider and cfg.same_provider_only:
        return RouteTarget(
            provider=provider, model=model, tier=decision.tier,
            confidence=decision.confidence,
            reason="cross-provider route suppressed (same_provider_only)",
            cross_provider=True,
        )

    return RouteTarget(
        provider=provider, model=model, tier=decision.tier,
        confidence=decision.confidence,
        reason=f"tier={decision.tier} conf={decision.confidence:.2f}",
        cross_provider=cross_provider,
    )
