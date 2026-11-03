"""Import a private SWElist inventory into its own SQLite table.

SWElist rows never become bot offers or application candidates by this import.
Matches on company and title are hints only, because distinct jobs share titles.
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import unicodedata
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

SCHEMA = """
CREATE TABLE IF NOT EXISTS swelist_annonces (
    simplify_id TEXT PRIMARY KEY,
    date_mail TEXT NOT NULL,
    id_mail TEXT NOT NULL,
    entreprise TEXT NOT NULL,
    intitule TEXT NOT NULL,
    lien_simplify TEXT NOT NULL UNIQUE,
    premier_filtre TEXT NOT NULL,
    raison TEXT NOT NULL,
    bot_cle_candidate TEXT,
    rapprochement TEXT NOT NULL DEFAULT 'aucun',
    label_humain INTEGER CHECK(label_humain IN (0, 1)),
    score_fit REAL CHECK(score_fit BETWEEN 0 AND 1),
    verdict_ml TEXT,
    version_modele TEXT,
    evalue_le TEXT
);
CREATE INDEX IF NOT EXISTS idx_swelist_rapprochement
    ON swelist_annonces(rapprochement);
CREATE INDEX IF NOT EXISTS idx_swelist_verdict
    ON swelist_annonces(verdict_ml);
"""


def normaliser(texte: str) -> str:
    ascii_texte = (
        unicodedata.normalize("NFKD", texte.casefold()).encode("ascii", "ignore").decode("ascii")
    )
    return re.sub(r"[^a-z0-9]+", " ", ascii_texte).strip()


def simplify_id(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in {"simplify.jobs", "www.simplify.jobs"}:
        raise ValueError("Lien SWElist non Simplify")
    match = re.fullmatch(r"/p/([0-9a-fA-F-]{36})/?", parsed.path)
    if not match:
        raise ValueError("Identifiant Simplify absent du lien")
    return match.group(1).lower()


def importer(db: sqlite3.Connection, inventory: Path) -> dict[str, int]:
    if not db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='offres'"
    ).fetchone():
        raise ValueError("Le registre du bot ne contient pas la table offres")
    with inventory.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {
            "date_mail",
            "id_mail",
            "entreprise",
            "intitule",
            "lien_simplify",
            "premier_filtre",
            "raison",
        }
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("Colonnes SWElist manquantes")
        entries = list(reader)
    ids = [simplify_id(row["lien_simplify"].strip()) for row in entries]
    if len(set(ids)) != len(ids):
        raise ValueError("Doublon d'identifiant Simplify dans le CSV")

    by_url: dict[str, set[str]] = defaultdict(set)
    by_title: dict[tuple[str, str], set[str]] = defaultdict(set)
    for key, company, title, url in db.execute("SELECT cle, entreprise, titre, url FROM offres"):
        if url:
            by_url[url.split("?", 1)[0].rstrip("/")].add(key)
        if company and title:
            by_title[(normaliser(company), normaliser(title))].add(key)

    counts = {
        "lues": len(entries),
        "ajoutees": 0,
        "deja_presentes": 0,
        "url_exacte": 0,
        "titre_entreprise_unique": 0,
        "titre_entreprise_ambigu": 0,
        "aucun": 0,
    }
    db.executescript(SCHEMA)
    with db:
        for sid, row in zip(ids, entries, strict=True):
            company, title = row["entreprise"].strip(), row["intitule"].strip()
            if not company or not title or not row["date_mail"] or not row["id_mail"]:
                raise ValueError(f"Ligne SWElist incomplète : {sid}")
            url = row["lien_simplify"].strip()
            url_matches = by_url.get(url.split("?", 1)[0].rstrip("/"), set())
            title_matches = by_title.get((normaliser(company), normaliser(title)), set())
            if len(url_matches) == 1:
                match, candidate = "url_exacte", next(iter(url_matches))
            elif len(title_matches) == 1:
                match, candidate = "titre_entreprise_unique", next(iter(title_matches))
            elif title_matches or url_matches:
                match, candidate = "titre_entreprise_ambigu", None
            else:
                match, candidate = "aucun", None
            counts[match] += 1
            exists = db.execute(
                "SELECT 1 FROM swelist_annonces WHERE simplify_id=?", (sid,)
            ).fetchone()
            counts["deja_presentes" if exists else "ajoutees"] += 1
            db.execute(
                """INSERT INTO swelist_annonces
                   (simplify_id,date_mail,id_mail,entreprise,intitule,lien_simplify,
                    premier_filtre,raison,bot_cle_candidate,rapprochement)
                   VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(simplify_id) DO UPDATE SET
                     date_mail=excluded.date_mail,
                     id_mail=excluded.id_mail,
                     entreprise=excluded.entreprise,
                     intitule=excluded.intitule,
                     lien_simplify=excluded.lien_simplify,
                     premier_filtre=excluded.premier_filtre,
                     raison=excluded.raison,
                     bot_cle_candidate=excluded.bot_cle_candidate,
                     rapprochement=excluded.rapprochement""",
                (
                    sid,
                    row["date_mail"],
                    row["id_mail"],
                    company,
                    title,
                    url,
                    row["premier_filtre"],
                    row["raison"],
                    candidate,
                    match,
                ),
            )
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    args = parser.parse_args()
    db = sqlite3.connect(args.db, timeout=30)
    try:
        print(importer(db, args.inventory))
    finally:
        db.close()


if __name__ == "__main__":
    main()
