"""hermes-model-router — local, no-LLM-call complexity routing for Hermes.

Registers an ``llm_request`` middleware that classifies each turn and (for
same-provider targets) swaps to a tier-appropriate model. See docs/PLAN.md for
the cross-provider story (goal-manager / upstream hook).
"""

from __future__ import annotations

import logging

from .config import RouterConfig
from .middleware import make_llm_request_middleware, make_model_request_middleware

__version__ = "0.1.5"
__all__ = ["register", "RouterConfig", "__version__"]

logger = logging.getLogger("hermes_model_router")


def register(ctx) -> None:
    """Hermes plugin entrypoint. ``ctx`` is the PluginContext.

    Config lives under the top-level ``model_router:`` key in config.yaml,
    read the same way other Hermes plugins read config.
    """
    raw = {}
    try:
        from hermes_cli.config import load_config, cfg_get
        raw = cfg_get(load_config(), "model_router", default={}) or {}
    except Exception:
        # Hermes not importable (e.g. unit tests) — fall back to defaults.
        raw = {}

    cfg = RouterConfig.from_mapping(raw)
    if not cfg.enabled:
        logger.info("hermes-model-router disabled via config; not registering middleware")
        return

    # model_request: cross-provider live routing — used on Hermes builds that
    # have the pre-model-selection seam (upstream/); ignored on stock builds.
    ctx.register_middleware("model_request", make_model_request_middleware(cfg))
    # llm_request: same-provider model swap — works on stock Hermes today.
    ctx.register_middleware("llm_request", make_llm_request_middleware(cfg))
    logger.info(
        "hermes-model-router registered (mode=%s, gate=%.2f, same_provider_only=%s, tiers=%s)",
        cfg.mode, cfg.gate_confidence, cfg.same_provider_only, list(cfg.tiers),
    )
