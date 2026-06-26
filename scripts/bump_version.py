#!/usr/bin/env python3
"""Bump the project version (semver x.y.z) and sync it everywhere.

Usage: bump_version.py [patch|minor|major]   (default: patch)

VERSION is the single source of truth; this also rewrites the version string in
pyproject.toml, plugin.yaml, and hermes_model_router/__init__.py so they never
drift. Run automatically by the pre-commit hook (.githooks/pre-commit).
"""
from __future__ import annotations

import re
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
PART = (sys.argv[1] if len(sys.argv) > 1 else "patch").lower()

vf = ROOT / "VERSION"
major, minor, patch = (int(x) for x in vf.read_text().strip().split("."))
if PART == "major":
    major, minor, patch = major + 1, 0, 0
elif PART == "minor":
    minor, patch = minor + 1, 0
elif PART == "patch":
    patch += 1
else:
    sys.exit(f"unknown bump part: {PART!r} (use patch|minor|major)")

new = f"{major}.{minor}.{patch}"
vf.write_text(new + "\n")


def _sub(rel: str, pattern: str, repl: str) -> None:
    p = ROOT / rel
    if not p.exists():
        return
    p.write_text(re.sub(pattern, repl, p.read_text(), count=1))


_sub("pyproject.toml", r'version = "[^"]+"', f'version = "{new}"')
_sub("hermes_model_router/plugin.yaml", r'version: "[^"]+"', f'version: "{new}"')
_sub("hermes_model_router/__init__.py", r'__version__ = "[^"]+"', f'__version__ = "{new}"')

print(new)
