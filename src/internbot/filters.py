"""Classement des offres : exclusions de la config, puis filtre v3 (filters_v3.py).

Toutes les comparaisons se font sur un texte normalisé :
- insensible à la casse et aux accents (« Stagiaire » == « stagiaire » == « STAGIAIRE ») ;
- ponctuation remplacée par des espaces (« Co-op » == « co op ») ;
- correspondance par mot entier : « intern » ne matche ni « internal » ni « internship ».
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from internbot import filters_v3
from internbot.config import FiltersConfig
from internbot.filters_v3 import DROP, Verdict
from internbot.models import Job

_NON_ALNUM = re.compile(r"[^0-9a-z]+")
_YEAR = re.compile(r"(?<![0-9])20[0-9]{2}(?![0-9])")


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


class JobClassifier:
    """Range une offre dans un seau du filtre v3 : notify, review ou drop.

    Avant le filtre v3, deux exclusions propres à la config : `title_exclude` (« senior »…)
    et `year_hint` (« Summer 2026 » quand on vise 2027).
    """

    def __init__(self, cfg: FiltersConfig) -> None:
        self.cfg = cfg
        self.title_exclude = TermMatcher(cfg.title_exclude)
        self.years = {y.strip() for y in cfg.year_hint if y.strip()}
        self.v3 = filters_v3.FilterConfig(
            enabled_regions=set(cfg.regions),
            include_data=cfg.include_data,
            include_fde=cfg.include_fde,
            include_quant_research=cfg.include_quant_research,
        )

    def title_verdict(self, title: str) -> Verdict:
        """Verdict sur le seul titre (étape bon marché, avant enrichissement du lieu)."""
        if (hit := self.title_exclude.find(title)) is not None:
            return Verdict(DROP, f"titre exclu ({hit!r})")
        if (reason := self._year_reject_reason(title)) is not None:
            return Verdict(DROP, reason)
        return filters_v3.classify_title(title, self.v3)

    def classify(self, job: Job) -> Verdict:
        verdict = self.title_verdict(job.title)
        if verdict.status == DROP:
            return verdict
        # Lieu partiel (Workday « 3 Locations » non résolu) : traité comme inconnu -> review.
        location = job.location if job.location_complete else ""
        return filters_v3.classify(job.title, location, self.v3)

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
