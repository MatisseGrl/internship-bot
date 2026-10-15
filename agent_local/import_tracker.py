"""Import du tracker Excel personnel de candidatures (onglets Europe et US).

Chaque ligne est conservée telle quelle dans la table privée `suivi_manuel`, puis reliée à
une offre du registre : identifiant d'offre cité dans les notes, URL précise, ou titre
identique et unique dans la même entreprise. Sinon une offre « tracker » est créée.
Les liens de tableau de bord (Google, Amazon…) ne servent jamais au rapprochement.

Un statut déclaré dans le tracker ne rétrograde jamais un statut déjà connu (refus,
entretien, test, action demandée). « À postuler » ne crée pas de candidature.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from contextlib import suppress
from datetime import date, datetime
from pathlib import Path

from agent import _etat_candidature, url_canonique
from import_swelist import normaliser
from suivi_candidatures import cle, maintenant

SCHEMA = """
CREATE TABLE IF NOT EXISTS suivi_manuel (
    feuille TEXT NOT NULL,
    numero INTEGER NOT NULL,
    cle_offre TEXT NOT NULL REFERENCES offres(cle),
    rapprochement TEXT NOT NULL,
    entreprise TEXT NOT NULL,
    poste TEXT NOT NULL,
    lieu TEXT,
    type TEXT,
    priorite TEXT,
    lien TEXT,
    source TEXT,
    date_candidature TEXT,
    statut TEXT,
    contact TEXT,
    date_relance TEXT,
    prochaine_action TEXT,
    date_maj TEXT,
    visa TEXT,
    notes TEXT,
    importe_le TEXT NOT NULL,
    PRIMARY KEY(feuille, numero)
);
CREATE TABLE IF NOT EXISTS reponses_candidature (
    feuille TEXT PRIMARY KEY,
    texte TEXT NOT NULL,
    importe_le TEXT NOT NULL
);
"""
COLONNES = {
    "N°": "numero",
    "Entreprise": "entreprise",
    "Poste": "poste",
    "Ville / Pays": "lieu",
    "Type": "type",
    "Priorité": "priorite",
    "Lien de l'offre": "lien",
    "Source": "source",
    "Date candidature": "date_candidature",
    "Statut": "statut",
    "Contact / Referral": "contact",
    "Date relance prévue": "date_relance",
    "Prochaine action": "prochaine_action",
    "Date dernière MAJ": "date_maj",
    "Visa (CPT/J-1)": "visa",
    "Notes": "notes",
}
STATUTS = {
    "Postulé": "envoyee",
    "Relancé": "envoyee",
    "Sans réponse": "envoyee",
    "Test technique": "evaluation",
    "Entretien RH": "entretien",
    "Entretien technique": "entretien",
    "Entretien final": "entretien",
    "Offre": "entretien",
    "Refusé": "refusee",
}
# Un statut plus avancé déjà enregistré (mail, export) n'est jamais écrasé.
PLUS_AVANCES = {"refusee", "entretien", "evaluation", "action_requise"}
# Pages de suivi du compte candidat : elles ne désignent pas une offre.
LIEN_GENERIQUE = re.compile(r"dashboard|/applications(\?|$)|/applicant\b", re.IGNORECASE)
IDENTIFIANT_NOTE = re.compile(r"\b(?:Job n°|ID)\s*([A-Z]*\d{5,})\b", re.IGNORECASE)


def _texte(valeur: object) -> str | None:
    if valeur is None:
        return None
    if isinstance(valeur, datetime | date):
        return valeur.strftime("%Y-%m-%d")
    texte = str(valeur).strip()
    return texte or None


def lire_classeur(chemin: Path) -> tuple[list[dict], dict[str, str]]:
    """Lit les onglets de candidatures et les onglets de réponses (une colonne de texte)."""
    import openpyxl  # dépendance optionnelle : pip install -e ".[agent]"

    classeur = openpyxl.load_workbook(chemin, data_only=True, read_only=True)
    lignes, reponses = [], {}
    for feuille in classeur.worksheets:
        valeurs = list(feuille.iter_rows(values_only=True))
        if not valeurs:
            continue
        entete = [_texte(v) for v in valeurs[0]]
        if "Entreprise" in entete and "Poste" in entete:
            for brut in valeurs[1:]:
                ligne = {
                    COLONNES[nom]: _texte(v)
                    for nom, v in zip(entete, brut, strict=False)
                    if nom in COLONNES
                }
                if ligne.get("entreprise") and ligne.get("poste"):
                    lignes.append({"feuille": feuille.title, **ligne})
        elif feuille.title.casefold().startswith("réponses"):
            texte = "\n".join(_texte(r[0]) or "" for r in valeurs if r and r[0] is not None)
            reponses[feuille.title] = texte
    return lignes, reponses


def _lien_precis(lien: str | None) -> str | None:
    if not lien or LIEN_GENERIQUE.search(lien):
        return None
    with suppress(ValueError):
        return url_canonique(lien)
    return None


def rapprocher(db: sqlite3.Connection, ligne: dict) -> tuple[str, str]:
    entreprise = ligne["entreprise"]
    noms = {entreprise, *(p.strip() for p in entreprise.split("/"))}
    for identifiant in IDENTIFIANT_NOTE.findall(ligne.get("notes") or ""):
        for nom in noms:
            if db.execute("SELECT 1 FROM offres WHERE cle=?", (cle(nom, identifiant),)).fetchone():
                return cle(nom, identifiant), "identifiant"
    lien = _lien_precis(ligne.get("lien"))
    if lien:
        for offre_cle, url in db.execute("SELECT cle,url FROM offres WHERE url IS NOT NULL"):
            with suppress(ValueError):
                if url_canonique(url) == lien:
                    return offre_cle, "url"
    titre = normaliser(ligne["poste"])
    memes = [
        offre_cle
        for offre_cle, offre_titre in db.execute(
            f"SELECT cle,titre FROM offres WHERE entreprise IN ({','.join('?' * len(noms))})",
            tuple(noms),
        )
        # Seules les offres d'une autre source comptent : deux lignes du tracker au même
        # titre (Londres et New York) sont deux candidatures distinctes.
        if offre_titre
        and normaliser(offre_titre) == titre
        and not offre_cle.split("\x1f", 1)[1].startswith("tracker-")
    ]
    if len(memes) == 1:
        return memes[0], "titre_unique"
    # Offre propre au tracker : identifiant stable tiré de la feuille et du numéro.
    identifiant = (
        "tracker-"
        + hashlib.sha256(f"{ligne['feuille']}\x1f{ligne['numero']}".encode()).hexdigest()[:12]
    )
    return cle(entreprise, identifiant), "nouvelle_offre"


def importer(db: sqlite3.Connection, lignes: list[dict], reponses: dict[str, str]) -> dict:
    db.executescript(SCHEMA)
    compte = {"lignes": 0, "rapprochees": 0, "offres_creees": 0, "candidatures": 0, "gardees": 0}
    with db:
        for ligne in lignes:
            compte["lignes"] += 1
            connue = db.execute(
                "SELECT cle_offre,rapprochement FROM suivi_manuel WHERE feuille=? AND numero=?",
                (ligne["feuille"], int(float(ligne["numero"]))),
            ).fetchone()
            offre_cle, mode = tuple(connue) if connue else rapprocher(db, ligne)
            if not db.execute("SELECT 1 FROM offres WHERE cle=?", (offre_cle,)).fetchone():
                db.execute(
                    """INSERT INTO offres(cle,entreprise,identifiant,titre,lieu,url,vu_le)
                       VALUES(?,?,?,?,?,?,?)""",
                    (
                        offre_cle,
                        ligne["entreprise"],
                        offre_cle.split("\x1f", 1)[1],
                        ligne["poste"],
                        ligne.get("lieu"),
                        _lien_precis(ligne.get("lien")) and ligne.get("lien"),
                        maintenant(),
                    ),
                )
                compte["offres_creees"] += 1
            elif mode != "nouvelle_offre":
                compte["rapprochees"] += 1
            champs = [c for c in COLONNES.values() if c != "numero"]
            db.execute(
                f"""INSERT INTO suivi_manuel(feuille,numero,cle_offre,rapprochement,
                       {",".join(champs)},importe_le)
                    VALUES(?,?,?,?,{",".join("?" * len(champs))},?)
                    ON CONFLICT(feuille,numero) DO UPDATE SET
                    {",".join(f"{c}=excluded.{c}" for c in [*champs, "importe_le"])}""",
                (
                    ligne["feuille"],
                    int(float(ligne["numero"])),
                    offre_cle,
                    mode,
                    *(ligne.get(c) for c in champs),
                    maintenant(),
                ),
            )
            statut = STATUTS.get(ligne.get("statut") or "")
            if not statut:
                continue
            if _etat_candidature(db, offre_cle) in PLUS_AVANCES:
                compte["gardees"] += 1
                continue
            preuve = (
                f"tracker:{ligne['feuille']}#{int(float(ligne['numero']))}:"
                f"{ligne['statut']} le {ligne.get('date_candidature') or 'date inconnue'}"
                " (déclaration de Matisse)"
            )
            db.execute(
                """INSERT INTO candidatures(cle_offre,statut,preuve,modifie_le) VALUES(?,?,?,?)
                   ON CONFLICT(cle_offre) DO UPDATE SET statut=excluded.statut,
                   preuve=excluded.preuve,modifie_le=excluded.modifie_le""",
                (offre_cle, statut, preuve, maintenant()),
            )
            compte["candidatures"] += 1
        for feuille, texte in reponses.items():
            db.execute(
                """INSERT INTO reponses_candidature(feuille,texte,importe_le) VALUES(?,?,?)
                   ON CONFLICT(feuille) DO UPDATE SET texte=excluded.texte,
                   importe_le=excluded.importe_le""",
                (feuille, texte, maintenant()),
            )
    return compte
