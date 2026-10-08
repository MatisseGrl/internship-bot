"""Interface des providers et registre nom -> classe.

Ajouter une plateforme = créer un fichier dans ce package avec une classe décorée par
`@register`. Le package importe automatiquement tous ses modules.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar, TypeVar

from internbot.errors import ProviderFormatError
from internbot.http import HttpClient
from internbot.models import Job

if TYPE_CHECKING:
    from internbot.config import CompanyConfig

REGISTRY: dict[str, type[Provider]] = {}

P = TypeVar("P", bound="type[Provider]")


def register(cls: P) -> P:
    name = cls.name
    if not name:
        raise TypeError(f"{cls.__name__} doit définir l'attribut de classe `name`")
    if name in REGISTRY and REGISTRY[name] is not cls:
        raise TypeError(f"Provider '{name}' déjà enregistré par {REGISTRY[name].__name__}")
    REGISTRY[name] = cls
    return cls


class Provider(ABC):
    name: ClassVar[str] = ""
    required_fields: ClassVar[tuple[str, ...]] = ()
    optional_fields: ClassVar[tuple[str, ...]] = ()

    def __init__(self, http: HttpClient) -> None:
        self.http = http

    @abstractmethod
    def fetch_jobs(self, company: CompanyConfig) -> list[Job]:
        """Retourne toutes les offres actuellement publiées (avant filtrage)."""

    def enrich(self, company: CompanyConfig, job: Job) -> Job:
        """Complète une offre candidate (lieu détaillé, date...). Par défaut : inchangée."""
        return job


# -- utilitaires partagés -----------------------------------------------------------------------


def require_key(data: Any, key: str, *, provider: str, kind: type = list) -> Any:
    """Lève ProviderFormatError si `data[key]` est absent ou du mauvais type."""
    if not isinstance(data, dict) or key not in data:
        keys = list(data)[:10] if isinstance(data, dict) else type(data).__name__
        raise ProviderFormatError(
            f"[{provider}] format de réponse inattendu : clé '{key}' absente (reçu : {keys})"
        )
    value = data[key]
    if not isinstance(value, kind):
        raise ProviderFormatError(
            f"[{provider}] '{key}' devrait être de type {kind.__name__}, "
            f"reçu {type(value).__name__}"
        )
    return value


def parse_items(
    items: Iterable[Any], parse: Callable[[dict[str, Any]], Job | None], *, provider: str
) -> list[Job]:
    """Parse chaque élément ; une offre mal formée est ignorée (et loggée) sans tout casser.
    Si AUCUNE offre n'est exploitable alors qu'il y en avait, c'est un changement de format."""
    import logging

    log = logging.getLogger(f"internbot.providers.{provider}")
    items = list(items)
    jobs: list[Job] = []
    bad = 0
    for item in items:
        try:
            job = parse(item) if isinstance(item, dict) else None
        except (KeyError, TypeError, ValueError) as exc:
            log.debug("Offre ignorée (%s) : %r", exc, item)
            job = None
        if job is None:
            log.debug("Offre incomplète ignorée : %r", item)
            bad += 1
        else:
            jobs.append(job)
    if bad:
        # Quelques fiches vides sont normales (ex: Workday renvoie parfois une offre masquée
        # réduite à son ID) ; une proportion importante signale un changement de format.
        level = logging.WARNING if bad > 0.1 * len(items) else logging.DEBUG
        log.log(
            level, "[%s] %d offre(s) mal formée(s) ignorée(s) sur %d", provider, bad, len(items)
        )
    if items and not jobs:
        raise ProviderFormatError(
            f"[{provider}] aucune des {len(items)} offres n'a pu être lue : format modifié ?"
        )
    return jobs


def iso_date(value: Any) -> str | None:
    """Normalise une date (ISO 8601, epoch ms) en 'YYYY-MM-DD'."""
    if value in (None, ""):
        return None
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value / 1000, tz=UTC).date().isoformat()
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text[:10] if len(text) >= 10 and text[4] == "-" else text


def join_locations(*parts: Any) -> str:
    """Concatène des lieux (str ou listes) sans doublons, dans l'ordre."""
    seen: list[str] = []
    for part in parts:
        values = part if isinstance(part, list | tuple) else [part]
        for value in values:
            text = str(value).strip() if value not in (None, "") else ""
            if text and text not in seen:
                seen.append(text)
    return " · ".join(seen)
