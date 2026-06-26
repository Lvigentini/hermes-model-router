"""Hermes ``llm_request`` middleware: classify the turn, rewrite the model.

IMPORTANT SEAM CONSTRAINT (verified against Hermes internals — see docs/PLAN.md):
``llm_request`` middleware can replace the request *body* (``api_kwargs``) but the
turn's provider/transport/credentials are already fixed before it runs. So this
middleware can only safely swap the **model within the current provider**.
Cross-provider routing (e.g. kimi → opus) needs the goal-manager/delegation path
or an upstream ``pre_model_selection`` hook; here it is detected and traced, not
applied (controlled by ``same_provider_only``).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .config import RouterConfig
from .determination import classify
from .tiers import resolve_route

logger = logging.getLogger("hermes_model_router")


def _latest_user_text(api_kwargs: Dict[str, Any]) -> str:
    """Extract the most recent user message text from an OpenAI/Responses body."""
    msgs = api_kwargs.get("messages")
    if not isinstance(msgs, list):
        msgs = api_kwargs.get("input")  # codex_responses shape
    if not isinstance(msgs, list):
        return ""
    for msg in reversed(msgs):
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):  # multimodal parts
            parts = [p.get("text", "") for p in content
                     if isinstance(p, dict) and p.get("type") in ("text", "input_text")]
            return "\n".join(parts)
    return ""


def make_llm_request_middleware(cfg: RouterConfig):
    """Build the middleware callable bound to ``cfg``."""

    def llm_request(request: Dict[str, Any] = None, **context: Any) -> Optional[Dict[str, Any]]:
        if not cfg.enabled or not isinstance(request, dict):
            return None
        try:
            text = _latest_user_text(request)
            if not text.strip():
                return None

            current_provider = str(context.get("provider") or "")
            current_model = str(context.get("model") or request.get("model") or "")

            decision = classify(text, ctx=context)
            route = resolve_route(
                decision, cfg,
                current_provider=current_provider,
                current_model=current_model,
            )
            if route is None:
                return None

            if route.cross_provider:
                # Cannot re-auth from here; surface it for the manager/hook path.
                logger.info(
                    "model-router: %s → would route to %s/%s but cross-provider "
                    "from %s is suppressed (%s)",
                    route.tier, route.provider, route.model,
                    current_provider, route.reason,
                )
                return {
                    "source": "hermes-model-router",
                    "reason": f"suppressed cross-provider → {route.provider}/{route.model}",
                }

            # Same-provider model swap — safe to apply.
            new_request = dict(request)
            new_request["model"] = route.model
            logger.info(
                "model-router: %s (conf %.2f) → model %s (was %s)",
                route.tier, route.confidence, route.model, current_model,
            )
            return {
                "request": new_request,
                "source": "hermes-model-router",
                "reason": route.reason,
            }
        except Exception as exc:  # never break the agent loop
            logger.warning("model-router middleware error: %s", exc)
            return None

    return llm_request
