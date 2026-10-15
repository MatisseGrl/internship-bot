"""Registre privé des offres et des candidatures. Aucun envoi de candidature."""

from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS offres (
    cle TEXT PRIMARY KEY,
    entreprise TEXT NOT NULL,
    identifiant TEXT NOT NULL,
    titre TEXT,
    lieu TEXT,
    url TEXT,
    texte TEXT,
    categorie_note TEXT,
    note_json TEXT,
    score REAL,
    dans_snapshot INTEGER NOT NULL DEFAULT 0,
    vu_le TEXT NOT NULL,
    UNIQUE(entreprise, identifiant)
);
CREATE TABLE IF NOT EXISTS candidatures (
    cle_offre TEXT PRIMARY KEY REFERENCES offres(cle),
    statut TEXT NOT NULL,
    cv TEXT,
    preuve TEXT,
    modifie_le TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mails (
    boite TEXT NOT NULL,
    identifiant_message TEXT NOT NULL,
    recu_le TEXT,
    expediteur TEXT,
    objet TEXT,
    categorie TEXT NOT NULL,
    cle_offre TEXT REFERENCES offres(cle),
    justification TEXT,
    traite_le TEXT NOT NULL,
    PRIMARY KEY(boite, identifiant_message)
);
CREATE INDEX IF NOT EXISTS idx_offres_snapshot ON offres(dans_snapshot, score);
CREATE INDEX IF NOT EXISTS idx_mails_offre ON mails(cle_offre);
"""

CATEGORIES_MAIL = {"confirmation", "refus", "entretien", "test", "action", "autre"}
STATUT_PAR_MAIL = {
    "confirmation": "envoyee",
    "refus": "refusee",
    "entretien": "entretien",
    "test": "evaluation",
}


def maintenant() -> str:
    return datetime.now(UTC).isoformat()


def cle(entreprise: str, identifiant: str) -> str:
    return f"{entreprise}\x1f{identifiant}"


def ouvrir(chemin: Path) -> sqlite3.Connection:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(chemin)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def synchroniser(
    db: sqlite3.Connection, notes: dict, archives: list[Path], snapshot: dict
) -> dict[str, int]:
    """Importer sans écraser les candidatures et les mails déjà enregistrés."""
    compte = {"notes": 0, "textes": 0, "ouvertes": 0}
    date = maintenant()
    if not isinstance(notes.get("offres"), dict) or not isinstance(notes.get("ecartees"), dict):
        raise ValueError("Format des notes non reconnu")
    if snapshot.get("version") != 1 or not isinstance(snapshot.get("companies"), dict):
        raise ValueError("Format du snapshot non reconnu")
    with db:
        for categorie, bloc in (("gardee", notes["offres"]), ("ecartee", notes["ecartees"])):
            for entreprise, offres in bloc.items():
                for identifiant, note in offres.items():
                    score = note.get("score") if isinstance(note, dict) else None
                    db.execute(
                        """INSERT INTO offres(cle, entreprise, identifiant, categorie_note,
                           note_json, score, vu_le) VALUES (?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(cle) DO UPDATE SET categorie_note=excluded.categorie_note,
                           note_json=excluded.note_json, score=excluded.score,
                           vu_le=excluded.vu_le""",
                        (
                            cle(entreprise, str(identifiant)),
                            entreprise,
                            str(identifiant),
                            categorie,
                            json.dumps(note, ensure_ascii=False),
                            score if isinstance(score, (int, float)) else None,
                            date,
                        ),
                    )
                    compte["notes"] += 1
        for chemin in archives:
            with chemin.open(encoding="utf-8") as fichier:
                for numero, ligne in enumerate(fichier, 1):
                    if not ligne.strip():
                        continue
                    try:
                        offre = json.loads(ligne)
                        entreprise = str(offre["company"])
                        identifiant = str(offre["job_id"])
                    except (ValueError, KeyError, TypeError) as erreur:
                        raise ValueError(f"Archive invalide : {chemin}:{numero}") from erreur
                    db.execute(
                        """INSERT INTO offres(cle, entreprise, identifiant, titre, lieu,
                           url, texte, vu_le) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(cle) DO UPDATE SET
                           titre=COALESCE(excluded.titre, offres.titre),
                           lieu=COALESCE(excluded.lieu, offres.lieu),
                           url=COALESCE(excluded.url, offres.url),
                           texte=CASE WHEN length(COALESCE(excluded.texte, '')) >
                               length(COALESCE(offres.texte, ''))
                               THEN excluded.texte ELSE offres.texte END,
                           vu_le=excluded.vu_le""",
                        (
                            cle(entreprise, identifiant),
                            entreprise,
                            identifiant,
                            offre.get("title"),
                            offre.get("location"),
                            offre.get("url"),
                            offre.get("texte"),
                            date,
                        ),
                    )
                    compte["textes"] += 1
        db.execute("UPDATE offres SET dans_snapshot = 0")
        for entreprise, bloc in snapshot["companies"].items():
            for offre in bloc.get("jobs", []):
                identifiant = str(offre["job_id"])
                db.execute(
                    """INSERT INTO offres(cle, entreprise, identifiant, titre, lieu,
                       url, dans_snapshot, vu_le) VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                       ON CONFLICT(cle) DO UPDATE SET titre=excluded.titre,
                       lieu=excluded.lieu, url=excluded.url, dans_snapshot=1,
                       vu_le=excluded.vu_le""",
                    (
                        cle(entreprise, identifiant),
                        entreprise,
                        identifiant,
                        offre.get("title"),
                        offre.get("location"),
                        offre.get("url"),
                        date,
                    ),
                )
                compte["ouvertes"] += 1
    return compte


def enregistrer_mail(
    db: sqlite3.Connection,
    *,
    boite: str,
    identifiant_message: str,
    categorie: str,
    recu_le: str = "",
    expediteur: str = "",
    objet: str = "",
    entreprise: str = "",
    identifiant_offre: str = "",
    justification: str = "",
) -> str:
    """Ne changer un statut que si le mail identifie exactement une offre connue."""
    if categorie not in CATEGORIES_MAIL:
        raise ValueError("Catégorie de mail inconnue")
    if not boite or not identifiant_message:
        raise ValueError("Boîte et identifiant du message requis")
    cle_offre = cle(entreprise, identifiant_offre) if entreprise and identifiant_offre else None
    if cle_offre and not db.execute("SELECT 1 FROM offres WHERE cle=?", (cle_offre,)).fetchone():
        cle_offre = None
    with db:
        curseur = db.execute(
            """INSERT OR IGNORE INTO mails(boite, identifiant_message, recu_le,
               expediteur, objet, categorie, cle_offre, justification, traite_le)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                boite,
                identifiant_message,
                recu_le,
                expediteur,
                objet,
                categorie,
                cle_offre,
                justification,
                maintenant(),
            ),
        )
        if curseur.rowcount == 0:
            return "deja_enregistre"
        if cle_offre and categorie in STATUT_PAR_MAIL:
            statut_actuel = db.execute(
                "SELECT statut FROM candidatures WHERE cle_offre=?", (cle_offre,)
            ).fetchone()
            # Un accusé de réception ancien ne doit pas effacer un refus, un test ou un entretien.
            if (
                categorie == "confirmation"
                and statut_actuel
                and statut_actuel[0] in {"refusee", "entretien", "evaluation", "action_requise"}
            ):
                return "mail_enregistre_sans_regression"
            db.execute(
                """INSERT INTO candidatures(cle_offre, statut, preuve, modifie_le)
                   VALUES (?, ?, ?, ?) ON CONFLICT(cle_offre) DO UPDATE SET
                   statut=excluded.statut, preuve=excluded.preuve,
                   modifie_le=excluded.modifie_le""",
                (
                    cle_offre,
                    STATUT_PAR_MAIL[categorie],
                    f"mail:{boite}:{identifiant_message}",
                    maintenant(),
                ),
            )
            return "statut_mis_a_jour"
    return "a_verifier"


def bilan(db: sqlite3.Connection) -> dict:
    return {
        "offres": db.execute("SELECT count(*) FROM offres").fetchone()[0],
        "notes": db.execute("SELECT count(*) FROM offres WHERE note_json IS NOT NULL").fetchone()[
            0
        ],
        "textes": db.execute("SELECT count(*) FROM offres WHERE texte IS NOT NULL").fetchone()[0],
        "dans_snapshot": db.execute("SELECT count(*) FROM offres WHERE dans_snapshot=1").fetchone()[
            0
        ],
        "mails": db.execute("SELECT count(*) FROM mails").fetchone()[0],
        "candidatures": db.execute("SELECT count(*) FROM candidatures").fetchone()[0],
        "mails_a_verifier": db.execute(
            """SELECT count(*) FROM mails
               WHERE categorie='action' OR (cle_offre IS NULL AND categorie!='autre')"""
        ).fetchone()[0],
    }


def main() -> None:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--db", type=Path, required=True)
    sous = parseur.add_subparsers(dest="commande", required=True)
    imp = sous.add_parser("synchroniser")
    imp.add_argument("--notes", type=Path, required=True)
    imp.add_argument("--archives", type=Path, nargs="+", required=True)
    imp.add_argument("--snapshot", type=Path, required=True)
    sous.add_parser("bilan")
    mail = sous.add_parser("mail")
    mail.add_argument("--boite", required=True)
    mail.add_argument("--message", required=True)
    mail.add_argument("--categorie", choices=sorted(CATEGORIES_MAIL), required=True)
    mail.add_argument("--recu-le", default="")
    mail.add_argument("--expediteur", default="")
    mail.add_argument("--objet", default="")
    mail.add_argument("--entreprise", default="")
    mail.add_argument("--id-offre", default="")
    mail.add_argument("--justification", default="")
    args = parseur.parse_args()
    with closing(ouvrir(args.db)) as db:
        if args.commande == "synchroniser":
            resultat = synchroniser(
                db,
                json.loads(args.notes.read_text(encoding="utf-8")),
                args.archives,
                json.loads(args.snapshot.read_text(encoding="utf-8-sig")),
            )
        elif args.commande == "mail":
            resultat = enregistrer_mail(
                db,
                boite=args.boite,
                identifiant_message=args.message,
                categorie=args.categorie,
                recu_le=args.recu_le,
                expediteur=args.expediteur,
                objet=args.objet,
                entreprise=args.entreprise,
                identifiant_offre=args.id_offre,
                justification=args.justification,
            )
        else:
            resultat = bilan(db)
    print(json.dumps(resultat, ensure_ascii=False))


if __name__ == "__main__":
    main()
