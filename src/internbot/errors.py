"""Hiérarchie d'exceptions du projet."""

from __future__ import annotations


class InternbotError(Exception):
    """Erreur de base du projet."""


class ConfigError(InternbotError):
    """Configuration invalide ou incomplète (config.yaml, variables d'environnement)."""


class HttpError(InternbotError):
    """Erreur HTTP définitive (après retries) ou réponse inexploitable."""

    def __init__(self, message: str, *, status: int | None = None, url: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.url = url


class ProviderError(InternbotError):
    """Une source d'offres a échoué (réseau, paramètres erronés...)."""


class ProviderFormatError(ProviderError):
    """La réponse d'une source n'a pas le format attendu (API modifiée ?)."""
