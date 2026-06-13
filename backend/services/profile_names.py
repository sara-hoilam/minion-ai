"""User profile first/last name helpers."""

from __future__ import annotations


def normalize_name_part(value: str | None) -> str:
    return (value or "").strip()


def sync_full_name(profile) -> None:
    first = normalize_name_part(getattr(profile, "first_name", None))
    last = normalize_name_part(getattr(profile, "last_name", None))
    if first or last:
        profile.full_name = f"{first} {last}".strip()


def apply_profile_names(profile, first_name: str | None, last_name: str | None) -> None:
    if first_name is not None:
        profile.first_name = normalize_name_part(first_name)
    if last_name is not None:
        profile.last_name = normalize_name_part(last_name)
    sync_full_name(profile)


def profile_name_parts(profile) -> tuple[str, str]:
    first = normalize_name_part(getattr(profile, "first_name", None) if profile else None)
    last = normalize_name_part(getattr(profile, "last_name", None) if profile else None)
    if first or last:
        return first, last
    full = normalize_name_part(getattr(profile, "full_name", None) if profile else None)
    if not full:
        return "", ""
    parts = full.split(None, 1)
    return parts[0], parts[1] if len(parts) > 1 else ""
