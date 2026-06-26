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
        # Fires on every Hermes build. Handles `announce` logging (for both
        # same- and cross-provider) and same-provider auto swaps. Cross-provider
        # auto swaps are left to the `model_request` seam.
        if not cfg.observing or not isinstance(request, dict):
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

            if not cfg.active:  # announce mode — show, don't switch
                logger.info(
                    "model-router[announce]: %s (conf %.2f) suggests %s/%s (current %s/%s)",
                    route.tier, route.confidence, route.provider, route.model,
                    current_provider, current_model,
                )
                return {"source": "hermes-model-router",
                        "reason": f"announce → {route.provider}/{route.model}"}

            if route.cross_provider:
                # Handled by the model_request seam on a patched build; here we
                # can't re-auth, so just surface the intent.
                logger.info(
                    "model-router: %s → %s/%s needs the model_request seam "
                    "(cross-provider); not switched here", route.tier,
                    route.provider, route.model,
                )
                return {"source": "hermes-model-router",
                        "reason": f"deferred cross-provider → {route.provider}/{route.model}"}

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
            logger.warning("model-router llm_request error: %s", exc)
            return None

    return llm_request


def make_model_request_middleware(cfg: RouterConfig):
    """Build the ``model_request`` middleware (the pre-model-selection seam).

    Unlike ``llm_request``, this fires before credentials are bound, so it CAN
    re-route across providers (kimi → opus / gpt-5.5). Requires a Hermes build
    with the ``model_request`` seam (see upstream/); on stock Hermes it is simply
    never invoked. The decision is local — no LLM call.
    """

    def model_request(request: Dict[str, Any] = None, user_message: str = "",
                      **context: Any) -> Optional[Dict[str, Any]]:
        # Only switches in `auto` mode; `announce` logging is done by the
        # always-present llm_request path to avoid double-reporting.
        if not cfg.active or not isinstance(request, dict):
            return None
        # User pinned a model (e.g. `/model`) and asked us to respect it.
        if cfg.respect_explicit_model and context.get("explicit_model"):
            logger.info("model-router[model_request]: explicit pin in effect — standing down")
            return None
        try:
            text = (user_message or "").strip()
            if not text:
                return None

            cur_provider = str(request.get("provider") or "")
            cur_model = str(request.get("model") or "")

            decision = classify(text, ctx=context)
            route = resolve_route(
                decision, cfg,
                current_provider=cur_provider,
                current_model=cur_model,
                allow_cross_provider=True,   # this seam can re-auth
            )
            if route is None:
                return None

            new_request = dict(request)
            new_request["model"] = route.model
            new_request["provider"] = route.provider
            if route.cross_provider:
                # Drop stale endpoint fields so the gateway resolves fresh
                # credentials/base_url/api_mode for the chosen provider.
                new_request["base_url"] = None
                new_request["api_mode"] = None
            logger.info(
                "model-router[model_request]: %s (conf %.2f) → %s/%s (was %s/%s)",
                route.tier, route.confidence, route.provider, route.model,
                cur_provider, cur_model,
            )
            return {
                "request": new_request,
                "source": "hermes-model-router",
                "reason": route.reason,
            }
        except Exception as exc:
            logger.warning("model-router model_request error: %s", exc)
            return None

    return model_request
