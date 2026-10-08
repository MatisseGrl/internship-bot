"""Filtrage des offres : mots-clés de titre, lieux, saison.

Toutes les comparaisons se font sur un texte normalisé :
- insensible à la casse et aux accents (« Stagiaire » == « stagiaire » == « STAGIAIRE ») ;
- ponctuation remplacée par des espaces (« Co-op » == « co op ») ;
- correspondance par mot entier : « intern » ne matche ni « internal » ni « internship ».
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from internbot.config import FiltersConfig
from internbot.models import Job

_NON_ALNUM = re.compile(r"[^0-9a-z]+")
_YEAR = re.compile(r"(?<![0-9])20[0-9]{2}(?![0-9])")
# Séparateurs entre plusieurs lieux d'une même offre (« · » interne, « ; » Greenhouse, « | »).
_LOCATION_SEP = re.compile(r"\s*[·;|]\s*")

NOTIFY, REVIEW, REJECT = "NOTIFY", "REVIEW", "REJECT"


def split_locations(location: str) -> list[str]:
    return [part for part in _LOCATION_SEP.split(location) if part.strip()]


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    no_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _NON_ALNUM.sub(" ", no_accents.casefold()).strip()


class TermMatcher:
    """Teste si un texte contient au moins un des termes, en mots entiers."""

    def __init__(self, terms: Iterable[str]) -> None:
        normalized = sorted({normalize(t) for t in terms if normalize(t)}, key=len, reverse=True)
        self.terms = normalized
        self._regex = (
            re.compile(
                r"(?<![0-9a-z])(?:" + "|".join(map(re.escape, normalized)) + r")(?![0-9a-z])"
            )
            if normalized
            else None
        )

    def __bool__(self) -> bool:
        return self._regex is not None

    def find(self, text: str) -> str | None:
        if self._regex is None:
            return None
        match = self._regex.search(normalize(text))
        return match.group(0) if match else None


class JobFilter:
    def __init__(self, cfg: FiltersConfig) -> None:
        self.cfg = cfg
        self.title_include = TermMatcher(cfg.title_include)
        self.title_exclude = TermMatcher(cfg.title_exclude)
        self.keywords_any = TermMatcher(cfg.keywords_any)
        self.locations_include = TermMatcher(cfg.locations_include)
        self.locations_exclude = TermMatcher(cfg.locations_exclude)
        self.years = {y.strip() for y in cfg.year_hint if y.strip()}

    def title_reject_reason(self, title: str) -> str | None:
        """Rejet basé sur le seul titre (étape bon marché, avant enrichissement)."""
        if self.title_include and self.title_include.find(title) is None:
            return "titre sans mot-clé de stage"
        if (hit := self.title_exclude.find(title)) is not None:
            return f"titre exclu ({hit!r})"
        if self.keywords_any and self.keywords_any.find(title) is None:
            return "titre sans mot-clé métier (keywords_any)"
        return self._year_reject_reason(title)

    def location_reject_reason(self, job: Job) -> str | None:
        # Lieu inconnu ou partiel (« 8 Locations ») : on ne rejette pas, mieux vaut une alerte
        # de trop qu'une offre manquée.
        if not job.location.strip() or not job.location_complete:
            return None
        # Offre multi-lieux : on ne la rejette que si AUCUN de ses lieux ne convient
        # (« Shanghai · Santa Clara » reste visible si seule la Chine est exclue).
        parts = split_locations(job.location)
        allowed = [p for p in parts if self.locations_exclude.find(p) is None]
        if not allowed:
            hit = self.locations_exclude.find(job.location)
            return f"lieu exclu ({hit!r})"
        if self.locations_include and not any(self.locations_include.find(p) for p in allowed):
            return f"lieu hors liste ({job.location})"
        return None

    def reject_reason(self, job: Job) -> str | None:
        return self.title_reject_reason(job.title) or self.location_reject_reason(job)

    def matches(self, job: Job) -> bool:
        return self.reject_reason(job) is None

    def classify(self, job: Job) -> str:
        """NOTIFY : passe tous les filtres (offre notifiée).
        REVIEW : vrai stage (mot-clé de stage, aucun mot exclu, lieu accepté) écarté seulement
        par `keywords_any` ou l'année : à regarder à la main, jamais notifié.
        REJECT : tout le reste. Sert aux statistiques (`--status`), pas à la notification."""
        if self.matches(job):
            return NOTIFY
        title = job.title
        if (
            (not self.title_include or self.title_include.find(title) is not None)
            and self.title_exclude.find(title) is None
            and self.location_reject_reason(job) is None
        ):
            return REVIEW
        return REJECT

    def _year_reject_reason(self, title: str) -> str | None:
        if not self.years or self.cfg.year_hint_mode == "off":
            return None
        found = set(_YEAR.findall(normalize(title)))
        if self.cfg.year_hint_mode == "require":
            return None if found & self.years else "année visée absente du titre"
        # prefer
        if found and not (found & self.years):
            return f"autre saison ({', '.join(sorted(found))})"
        return None
