"""Notation des offres avec la grille de Matisse (`notation/GRILLE.md`) et verdicts.

Score /100 = (Fit×45 + Écosystème×20 + Pont×20 + Apprentissage×15) / 5, seuil 65 : poids et
seuil recopiés de l'onglet Barème du kit de notation (B5:D8 et B11). Deux variantes de poids
servent au verdict « Limite » (passe avec un jeu de poids et pas avec un autre).

Qui note quoi :
- Écosystème SF et Pont vers SF hors US dépendent de l'ENTREPRISE : `notation/entreprises.yaml`
  (une note et sa preuve par entreprise, écrites une fois) ;
- Fit, Apprentissage, éligibilité, lieu US et conditions dépendent de l'OFFRE : notés à la
  lecture du texte de l'annonce, chacun avec une citation exacte du texte (vérifiée ici :
  une citation introuvable dans l'offre rejette la note, rien n'est inventé).

Verdicts (`notation/notes.json`) :
- `retenue` : score >= 65 ;
- `limite`  : score < 65 mais >= 65 avec une variante de poids (à trancher par Matisse : gardée) ;
- `a_trancher` : pas un stage (alternance, CDI, VIE) : gardée, à trancher par Matisse ;
- `illisible` : texte de l'annonce inaccessible : gardée, à trier à la main ;
- écartée (non éligible, ou score < 65 avec tous les jeux de poids) : seul l'identifiant est
  conservé, pour la cacher de /offres ; la note n'est pas gardée.
Une offre absente du fichier n'est pas encore notée : elle reste visible.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from internbot.errors import ConfigError

NOTES_VERSION = 1

CRITERES = ("fit", "eco", "pont", "app")
POIDS = {"fit": 45, "eco": 20, "pont": 20, "app": 15}
VARIANTES = {
    "SF-first": {"fit": 45, "eco": 25, "pont": 20, "app": 10},
    "Apprentissage": {"fit": 45, "eco": 15, "pont": 10, "app": 30},
}
SEUIL = 65

RETENUE, LIMITE, A_TRANCHER, ILLISIBLE, ECARTEE = (
    "retenue",
    "limite",
    "a_trancher",
    "illisible",
    "ecartee",
)
GARDEES = (RETENUE, LIMITE, A_TRANCHER, ILLISIBLE)
MOTIFS_INELIGIBLE = {
    "fin_etudes": "stage de fin d'études uniquement",
    "niveau": "niveau, école ou date de diplôme imposés que Matisse n'a pas",
    "phd": "PhD uniquement",
    "fermee": "offre expirée ou fermée",
    "nationalite": "nationalité, habilitation ou visa impossible",
    "dates": "dates totalement incompatibles",
    # Décision de Matisse (11 oct. 2026) : aucun poste de recherche, même appliquée.
    "recherche": "poste de recherche (Research Intern, Researcher, Research Scientist, thèse)",
}
NON_PRECISE = "non précisé"
MIN_MOTS_CITATION = 3


def score(notes: Mapping[str, int], poids: Mapping[str, int] = POIDS) -> float:
    """Somme(note × poids) / 5 : la formule de la grille (20 à 100)."""
    return sum(notes[c] * poids[c] for c in CRITERES) / 5


def verdict(notes: Mapping[str, int]) -> tuple[float, str]:
    """(score principal, retenue | limite | ecartee)."""
    principal = score(notes)
    if principal >= SEUIL:
        return principal, RETENUE
    if any(score(notes, p) >= SEUIL for p in VARIANTES.values()):
        return principal, LIMITE
    return principal, ECARTEE


# -- citations ---------------------------------------------------------------------------------

_QUOTES = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "«": '"', "»": '"'})


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_QUOTES).casefold()
    return " ".join(re.sub(r"[\"'`*•·]", " ", text).replace(" - ", " ").split())


def citation_presente(citation: str, texte: str) -> bool:
    """La citation figure-t-elle dans le texte (casse, espaces et guillemets ignorés) ?"""
    c = _plain(citation)
    return len(c.split()) >= MIN_MOTS_CITATION and c in _plain(texte)


# -- entreprises (Écosystème, Pont hors US) ----------------------------------------------------


@dataclass(frozen=True)
class Entreprise:
    eco: int
    eco_preuve: str
    pont: int  # Pont vers SF quand le stage n'est PAS aux États-Unis
    pont_preuve: str


def load_entreprises(path: Path) -> dict[str, Entreprise]:
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} : un objet YAML « Entreprise: {{eco, pont…}} » est attendu")
    out: dict[str, Entreprise] = {}
    errors = []
    for name, data in raw.items():
        try:
            ent = Entreprise(
                eco=int(data["eco"]),
                eco_preuve=str(data["eco_preuve"]).strip(),
                pont=int(data["pont"]),
                pont_preuve=str(data["pont_preuve"]).strip(),
            )
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"{name} : champ manquant ou invalide ({exc})")
            continue
        if not (1 <= ent.eco <= 5 and 1 <= ent.pont <= 4):
            errors.append(f"{name} : eco doit être entre 1 et 5, pont (hors US) entre 1 et 4")
        elif not ent.eco_preuve or not ent.pont_preuve:
            errors.append(f"{name} : chaque note demande une preuve")
        else:
            out[str(name)] = ent
    if errors:
        raise ConfigError(f"{path} invalide :\n  - " + "\n  - ".join(errors))
    return out


# -- fichier des verdicts ----------------------------------------------------------------------


class Notation:
    """`notation/notes.json` : verdict de chaque offre notée."""

    def __init__(self, path: Path | None, data: dict[str, Any] | None = None) -> None:
        self.path = path
        self.data: dict[str, Any] = data or {"version": NOTES_VERSION, "offres": {}, "ecartees": {}}
        self.data.setdefault("offres", {})
        self.data.setdefault("ecartees", {})
        self._ecartees = {
            (company, str(job_id))
            for company, ids in self.data["ecartees"].items()
            for job_id in ids
        }

    @classmethod
    def load(cls, path: Path) -> Notation:
        if not path.is_file():
            return cls(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{path} illisible : {exc}") from None
        if not isinstance(data, dict) or data.get("version") != NOTES_VERSION:
            raise ConfigError(f"{path} : version de fichier non supportée")
        return cls(path, data)

    def __len__(self) -> int:
        return len(self._ecartees) + sum(len(v) for v in self.data["offres"].values())

    def est_ecartee(self, company: str, job_id: str) -> bool:
        return (company, job_id) in self._ecartees

    def entree(self, company: str, job_id: str) -> dict[str, Any] | None:
        entry = (self.data["offres"].get(company) or {}).get(job_id)
        return dict(entry) if isinstance(entry, dict) else None

    def est_notee(self, company: str, job_id: str) -> bool:
        return self.est_ecartee(company, job_id) or self.entree(company, job_id) is not None

    def gardee(self, company: str, job_id: str, entry: Mapping[str, Any]) -> None:
        self._retirer(company, job_id)
        self.data["offres"].setdefault(company, {})[job_id] = dict(entry)

    def ecartee(self, company: str, job_id: str) -> None:
        self._retirer(company, job_id)
        ids = self.data["ecartees"].setdefault(company, [])
        ids.append(job_id)
        ids.sort()
        self._ecartees.add((company, job_id))

    def _retirer(self, company: str, job_id: str) -> None:
        offres = self.data["offres"].get(company) or {}
        offres.pop(job_id, None)
        if job_id in (self.data["ecartees"].get(company) or []):
            self.data["ecartees"][company].remove(job_id)
        self._ecartees.discard((company, job_id))

    def save(self) -> None:
        if self.path is None:
            return
        self.data["offres"] = {k: v for k, v in sorted(self.data["offres"].items()) if v}
        self.data["ecartees"] = {k: v for k, v in sorted(self.data["ecartees"].items()) if v}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.data, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
        fd, tmp = tempfile.mkstemp(prefix=".notes-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(payload)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


# -- import des notes d'offres -----------------------------------------------------------------


@dataclass
class ImportReport:
    statuts: dict[str, int] = field(default_factory=dict)
    erreurs: list[str] = field(default_factory=list)
    # (entreprise, titre, verdict, score) de chaque note acceptée, pour --simulation.
    verdicts: list[tuple[str, str, str, int | None]] = field(default_factory=list)

    def compter(self, statut: str) -> None:
        self.statuts[statut] = self.statuts.get(statut, 0) + 1


def _entier(note: Mapping[str, Any], key: str) -> int:
    value = note.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
        raise ValueError(f"{key} doit être un entier de 1 à 5 (reçu {value!r})")
    return value


def _citation(note: Mapping[str, Any], key: str, texte: str) -> str:
    citation = str(note.get(key) or "").strip()
    if not citation_presente(citation, texte):
        raise ValueError(f"{key} : citation absente du texte de l'offre ({citation[:80]!r})")
    return citation


def evaluer(
    note: Mapping[str, Any], offre: Mapping[str, Any], entreprise: Entreprise
) -> dict[str, Any]:
    """Valide la note d'une offre (citations comprises) et calcule son verdict.

    `offre` : ligne de l'export (texte de l'annonce, lieu…). Lève ValueError si la note est
    incomplète ou si une citation ne figure pas dans le texte.
    """
    # L'intitulé fait partie de l'offre : il peut servir de preuve (ex. motif `recherche`).
    texte = "\n".join(str(offre.get(k) or "") for k in ("title", "location", "texte"))
    if note.get("eligible") is False:
        motif = str(note.get("motif") or "")
        if motif not in MOTIFS_INELIGIBLE:
            raise ValueError(
                f"motif d'inéligibilité inconnu {motif!r} ({sorted(MOTIFS_INELIGIBLE)})"
            )
        _citation(note, "preuve_motif", texte)
        return {"statut": ECARTEE}
    if note.get("eligible") is not True:
        raise ValueError("eligible doit valoir true ou false")

    fit = _entier(note, "fit")
    _citation(note, "preuve_fit", texte)
    app = _entier(note, "app")
    preuve_app = str(note.get("preuve_app") or "").strip()
    if preuve_app.casefold() == NON_PRECISE:
        if app > 3:  # règle « information absente » : 3 au maximum
            raise ValueError("app > 3 sans citation (rien sur l'encadrement ni la prod)")
    else:
        _citation(note, "preuve_app", texte)

    if note.get("lieu_us") is True:
        _citation(note, "preuve_lieu", texte)
        pont, preuve_pont = 5, f"stage aux États-Unis : « {note['preuve_lieu']} »"
    elif note.get("lieu_us") is False:
        pont, preuve_pont = entreprise.pont, entreprise.pont_preuve
        if note.get("pont_offre") is not None:
            pont_offre = _entier(note, "pont_offre")
            if pont_offre > pont:
                pont = pont_offre
                preuve_pont = f"« {_citation(note, 'preuve_pont', texte)} »"
    else:
        raise ValueError("lieu_us doit valoir true ou false")

    notes = {"fit": fit, "eco": entreprise.eco, "pont": pont, "app": app}
    principal, statut = verdict(notes)
    if note.get("stage") is False and statut != ECARTEE:
        statut = A_TRANCHER  # alternance / CDI / VIE : Matisse décide (grille, cas particuliers)
    elif note.get("stage") not in (True, False):
        raise ValueError("stage doit valoir true ou false")
    if statut == ECARTEE:
        return {"statut": ECARTEE}
    return {
        "statut": statut,
        "score": round(principal),
        "notes": [notes[c] for c in CRITERES],
        "preuves": {
            "fit": f"« {note['preuve_fit']} »",
            "eco": entreprise.eco_preuve,
            "pont": preuve_pont,
            "app": f"« {preuve_app} »" if preuve_app.casefold() != NON_PRECISE else NON_PRECISE,
        },
        "conditions": str(note.get("conditions") or NON_PRECISE).strip(),
    }


def importer(
    notation: Notation,
    offres: Iterable[Mapping[str, Any]],
    notes: Iterable[Mapping[str, Any]],
    entreprises: Mapping[str, Entreprise],
) -> ImportReport:
    """Applique des notes d'offres (validées) et les offres illisibles au fichier de verdicts."""
    report = ImportReport()
    par_cle = {(str(o["company"]), str(o["job_id"])): o for o in offres}
    notees: set[tuple[str, str]] = set()
    for note in notes:
        key = (str(note.get("company")), str(note.get("job_id")))
        offre = par_cle.get(key)
        if offre is None:
            report.erreurs.append(f"{key} : offre absente de l'export")
            continue
        entreprise = entreprises.get(key[0])
        if entreprise is None:
            report.erreurs.append(f"{key} : entreprise absente de entreprises.yaml")
            continue
        try:
            entry = evaluer(note, offre, entreprise)
        except ValueError as exc:
            report.erreurs.append(f"{key[0]} / {offre.get('title')} ({key[1]}) : {exc}")
            continue
        notees.add(key)
        statut = entry.pop("statut")
        report.compter(statut)
        report.verdicts.append((key[0], str(offre.get("title")), statut, entry.get("score")))
        if statut == ECARTEE:
            notation.ecartee(*key)
        else:
            notation.gardee(*key, {"statut": statut, **entry})
    for key, offre in par_cle.items():
        if offre.get("erreur") and key not in notees and not notation.est_notee(*key):
            notation.gardee(*key, {"statut": ILLISIBLE, "motif": str(offre["erreur"])[:200]})
            report.compter(ILLISIBLE)
    return report
