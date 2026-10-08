"""Modèle de données central : une offre d'emploi normalisée."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any


@dataclass(frozen=True)
class Job:
    """Une offre normalisée, indépendante de la plateforme source.

    `job_id` est l'identifiant stable fourni par la plateforme (ex: `JR340771` chez Workday).
    La clé unique d'une offre est `(company, job_id)`.
    """

    company: str
    job_id: str
    title: str
    url: str
    source: str
    location: str = ""
    posted_at: str | None = None
    # False quand la plateforme ne donne qu'un résumé du lieu (ex: Workday « 8 Locations »).
    # Le filtre de lieu ne rejette jamais une offre dont le lieu est incomplet.
    location_complete: bool = True
    # Données propres au provider (ex: chemin Workday pour l'enrichissement). Hors égalité.
    extra: dict[str, Any] = field(default_factory=dict, compare=False, hash=False, repr=False)

    @property
    def key(self) -> tuple[str, str]:
        return (self.company, self.job_id)

    def with_updates(self, **changes: Any) -> Job:
        return replace(self, **changes)
