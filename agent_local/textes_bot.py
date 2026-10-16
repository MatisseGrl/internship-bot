"""Range dans `offres.texte` les textes exportés par `python -m internbot --exporter-textes`.

Seules les offres connues du registre et encore sans texte exploitable sont complétées :
un texte déjà présent (celui qui a servi à une note de grille, par exemple) n'est jamais
remplacé. Les lignes en erreur sont comptées et ignorées.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from suivi_candidatures import cle

TEXTE_MINIMUM = 300


def importer(db: sqlite3.Connection, export: Path) -> dict[str, int]:
    compte = {"lues": 0, "ajoutees": 0, "deja_texte": 0, "inconnues": 0, "erreurs": 0}
    with export.open(encoding="utf-8") as fichier, db:
        for ligne in fichier:
            if not ligne.strip():
                continue
            entree = json.loads(ligne)
            compte["lues"] += 1
            texte = entree.get("texte") or ""
            if entree.get("erreur") or len(texte) < TEXTE_MINIMUM:
                compte["erreurs"] += 1
                continue
            offre = db.execute(
                "SELECT texte FROM offres WHERE cle=?",
                (cle(entree["company"], str(entree["job_id"])),),
            ).fetchone()
            if offre is None:
                compte["inconnues"] += 1
            elif offre[0] and len(offre[0]) >= TEXTE_MINIMUM:
                compte["deja_texte"] += 1
            else:
                db.execute(
                    "UPDATE offres SET texte=? WHERE cle=?",
                    (texte, cle(entree["company"], str(entree["job_id"]))),
                )
                compte["ajoutees"] += 1
    return compte


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("export", type=Path)
    args = parser.parse_args()
    db = sqlite3.connect(args.db, timeout=60)
    try:
        print(json.dumps(importer(db, args.export), ensure_ascii=False))
    finally:
        db.close()


if __name__ == "__main__":
    main()
