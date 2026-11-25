"""Perfis de instituição: o que é específico de cada banco (ver `base.py`)."""

from __future__ import annotations

from findash.institutions.base import DescriptionPatterns, InstitutionProfile
from findash.institutions.nubank import NubankProfile

GENERIC = InstitutionProfile()
PROFILES: dict[str, InstitutionProfile] = {profile.key: profile for profile in (GENERIC, NubankProfile())}


def get_profile(key: str | None) -> InstitutionProfile:
    return PROFILES.get(key or GENERIC.key, GENERIC)


def is_known(key: str) -> bool:
    return key in PROFILES


__all__ = ["GENERIC", "PROFILES", "DescriptionPatterns", "InstitutionProfile", "get_profile", "is_known"]
