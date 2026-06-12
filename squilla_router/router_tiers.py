"""Canonical router tier identifiers and legacy aliases."""
from __future__ import annotations
from collections.abc import Mapping
from typing import Any

TEXT_TIERS: tuple[str, str, str, str] = ("c0", "c1", "c2", "c3")
DEFAULT_TEXT_TIER = "c1"
HIGHEST_TEXT_TIER = "c3"
IMAGE_TIER = "image_model"

LEGACY_TEXT_TIER_ALIASES: dict[str, str] = {
    "t0": "c0", "t1": "c1", "t2": "c2", "t3": "c3",
}
ROUTE_CLASS_TO_TIER: dict[str, str] = {
    "R0": "c0", "R1": "c1", "R2": "c2", "R3": "c3",
}
TIER_TO_ROUTE_CLASS: dict[str, str] = {v: k for k, v in ROUTE_CLASS_TO_TIER.items()}


def normalize_text_tier(value: object) -> str | None:
    raw = str(value).strip()
    if not raw:
        return None
    lower = raw.lower()
    if lower in TEXT_TIERS:
        return lower
    if lower in LEGACY_TEXT_TIER_ALIASES:
        return LEGACY_TEXT_TIER_ALIASES[lower]
    return None


def tier_index(value: object) -> int:
    tier = normalize_text_tier(value)
    if tier is None:
        return -1
    try:
        return TEXT_TIERS.index(tier)
    except ValueError:
        return -1


def normalize_target_id(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw == IMAGE_TIER:
        return IMAGE_TIER
    return normalize_text_tier(raw) or ""


def iter_text_tier_mapping(
    mapping: Mapping[str, Any],
) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in mapping.items():
        tier = normalize_target_id(key)
        out_key = tier or str(key)
        if out_key in normalized and str(key).strip().lower() not in TEXT_TIERS:
            continue
        normalized[out_key] = value
    return normalized
