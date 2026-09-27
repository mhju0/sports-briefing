"""Server-side public deployment source policy.

Public mode is an operator setting, never a client parameter. It encodes the
rights matrix in docs/feasibility.md: no source is currently cleared for public
display of timeline items, so provider-derived candidates are excluded before
ranking and Texans/Scottie use labelled synthetic demo candidates instead.
"""
from __future__ import annotations

import os
from typing import Mapping


PUBLIC_MODE_ENV = "SPORTS_BRIEFING_PUBLIC_MODE"

# Per-entity data source in each mode, as exposed by GET /meta.
DEV_ENTITY_SOURCES = {"arsenal": "provider", "texans": "provider", "scheffler": "provider"}
PUBLIC_ENTITY_SOURCES = {"arsenal": "unavailable", "texans": "demo", "scheffler": "demo"}


def public_mode_from_env(environ: Mapping[str, str] = os.environ) -> bool:
    value = environ.get(PUBLIC_MODE_ENV, "")
    if value in ("", "false"):
        return False
    if value == "true":
        return True
    # A typo must not silently fall back to development behavior.
    raise ValueError(f"{PUBLIC_MODE_ENV} must be 'true' or 'false'")


def entity_sources(public_mode: bool) -> dict[str, str]:
    return dict(PUBLIC_ENTITY_SOURCES if public_mode else DEV_ENTITY_SOURCES)
