"""Providers d'offres. Tous les modules du package sont importés automatiquement pour
peupler le registre : ajouter une plateforme = ajouter un fichier."""

from __future__ import annotations

import importlib
import pkgutil

from internbot.providers.base import REGISTRY, Provider, register

for _mod in pkgutil.iter_modules(__path__):
    if _mod.name != "base":
        importlib.import_module(f"{__name__}.{_mod.name}")


def get_provider_class(name: str) -> type[Provider]:
    return REGISTRY[name]


def available_providers() -> list[str]:
    return sorted(REGISTRY)


__all__ = ["REGISTRY", "Provider", "available_providers", "get_provider_class", "register"]
