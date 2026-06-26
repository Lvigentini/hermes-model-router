"""Detect an explicit in-message model directive, e.g. "use opus to …".

Local, no-LLM, regex-based. A directive requires an instruction verb in front of
a known model name/alias ("use opus", "with gpt-5.5", "ask gemini to …") so plain
topical mentions ("explain the opera Opus 27") don't trigger it. When found, the
router treats it as an explicit per-turn choice that overrides the heuristic and
any session pin.
"""

from __future__ import annotations

import re
from typing import Dict, Optional

# Common nicknames → {provider, model}. Defaults match the typical Hermes setup;
# users override/extend via `model_router.aliases`, and the configured tiers add
# their own names automatically (see RouterConfig.resolved_aliases).
BUILTIN_ALIASES: Dict[str, Dict[str, str]] = {
    "opus":     {"provider": "anthropic", "model": "claude-opus-4-8"},
    "sonnet":   {"provider": "anthropic", "model": "claude-sonnet-4-6"},
    "haiku":    {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
    "claude":   {"provider": "anthropic", "model": "claude-opus-4-8"},
    "gpt-5.5":  {"provider": "openai-codex", "model": "gpt-5.5"},
    "gpt5.5":   {"provider": "openai-codex", "model": "gpt-5.5"},
    "gpt":      {"provider": "openai-codex", "model": "gpt-5.5"},
    "chatgpt":  {"provider": "openai-codex", "model": "gpt-5.5"},
    "codex":    {"provider": "openai-codex", "model": "gpt-5.5"},
    "openai":   {"provider": "openai-codex", "model": "gpt-5.5"},
    "kimi":     {"provider": "kimi-coding", "model": "kimi-for-coding"},
    "gemini":   {"provider": "google-gemini-cli", "model": "gemini-3-pro"},
}

# Instruction verbs that must precede the model name. Word-bounded so "asked"
# does not match "ask". An optional article ("the"/"a"/"your") is allowed.
_VERBS = (
    r"(?:use|using|with|via|ask|run\s+(?:this\s+)?on|route\s+to|switch\s+to|"
    r"prefer|on)"
)
_ARTICLE = r"(?:the\s+|a\s+|an\s+|your\s+)?"


def detect_directive(text: str, aliases: Dict[str, Dict[str, str]]) -> Optional[Dict[str, str]]:
    """Return ``{provider, model, phrase}`` for an explicit directive, or None.

    Longest alias names are tried first so "gpt-5.5" wins over "gpt".
    """
    if not text:
        return None
    for name in sorted(aliases, key=len, reverse=True):
        target = aliases.get(name) or {}
        if not target.get("provider") or not target.get("model"):
            continue
        pat = re.compile(
            r"\b" + _VERBS + r"\s+" + _ARTICLE + re.escape(name) + r"\b",
            re.IGNORECASE,
        )
        m = pat.search(text)
        if m:
            return {
                "provider": target["provider"],
                "model": target["model"],
                "phrase": " ".join(m.group(0).split()),
            }
    return None
