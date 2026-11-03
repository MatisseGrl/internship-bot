"""Tri automatique des offres non notées : modèle TF-IDF figé sur le texte de l'offre.

Appris sur les offres notées avec la grille (`notation/notes.json`), comparé aux autres
pistes dans `docs/RECHERCHE_FAUX_POSITIFS.md` (test du 2 nov. 2026 : 97 % des offres
pertinentes gardées, 40 % des offres affichées). L'artefact `notation/tri_tfidf.json.gz`
contient le vocabulaire, les idf, les poids de la régression logistique et le seuil : le bot
note une offre sans scikit-learn, avec exactement les mêmes calculs (`TfidfVectorizer` mots
1-2 + caractères 3-5 `char_wb`, `sublinear_tf`, normes L2 séparées, puis produit scalaire).

Le score est un log-odds : au-dessous du seuil, l'offre est masquée de /offres et n'est pas
notifiée. Une offre déjà notée avec la grille garde le verdict de la grille.
"""

from __future__ import annotations

import gzip
import json
import math
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from internbot.errors import ConfigError

# Motif de mots par défaut de scikit-learn : deux caractères de mot ou plus.
_MOT = re.compile(r"(?u)\b\w\w+\b")
_ESPACES = re.compile(r"\s\s+")


def _mots(texte: str) -> Iterable[str]:
    jetons = _MOT.findall(texte)
    yield from jetons
    yield from (f"{a} {b}" for a, b in pairwise(jetons))


def _caracteres(texte: str) -> Iterable[str]:
    """N-grammes de caractères 3 à 5 à l'intérieur des mots bordés d'espaces (`char_wb`)."""
    for mot in _ESPACES.sub(" ", texte).split():
        mot = f" {mot} "
        for n in range(3, 6):
            debut = 0
            yield mot[debut : debut + n]
            while debut + n < len(mot):
                debut += 1
                yield mot[debut : debut + n]
            if debut == 0:  # mot plus court que n : une seule fois, comme scikit-learn
                break


def _partie(termes: Iterable[str], table: dict[str, list[float]]) -> float:
    """Contribution d'un vectoriseur : sum(poids * tfidf) / norme L2 du vecteur tfidf."""
    comptes = Counter(t for t in termes if t in table)
    produit, norme = 0.0, 0.0
    for terme, n in comptes.items():
        idf, poids = table[terme]
        valeur = (1.0 + math.log(n)) * idf
        produit += poids * valeur
        norme += valeur * valeur
    return produit / math.sqrt(norme) if norme else 0.0


@dataclass(frozen=True)
class ModeleTri:
    version: str
    seuil: float
    biais: float
    texte_max: int
    mots: dict[str, list[float]]
    caracteres: dict[str, list[float]]

    @classmethod
    def load(cls, path: Path) -> ModeleTri:
        try:
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                data = json.load(fh)
            return cls(
                version=str(data["version"]),
                seuil=float(data["seuil"]),
                biais=float(data["biais"]),
                texte_max=int(data["texte_max"]),
                mots=data["mots"],
                caracteres=data["caracteres"],
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ConfigError(f"{path} : modèle de tri illisible ({exc})") from None

    def score(self, titre: str, texte: str) -> float:
        document = f"{titre}\n{texte[: self.texte_max]}".lower()
        return (
            self.biais
            + _partie(_mots(document), self.mots)
            + _partie(_caracteres(document), self.caracteres)
        )

    def garder(self, score: float) -> bool:
        return score >= self.seuil
