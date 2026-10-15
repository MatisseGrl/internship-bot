"""Export a title-review sample and import human Fit-role labels (0 or 1).

These labels are kept separate from the bot's historical scores and are not
automatically fed into training. They form an independent SWElist audit set.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sqlite3
from pathlib import Path


FIELDS = ["groupe", "simplify_id", "entreprise", "intitule", "lien_simplify",
          "premier_filtre", "score_fit", "verdict_ml", "label_humain"]


def export_review(db: sqlite3.Connection, output: Path) -> dict[str, int]:
    db.row_factory = sqlite3.Row
    rows = [dict(row) for row in db.execute(
        """SELECT simplify_id,entreprise,intitule,lien_simplify,premier_filtre,
                  score_fit,verdict_ml,label_humain
           FROM swelist_annonces WHERE score_fit IS NOT NULL AND label_humain IS NULL"""
    )]
    low = [row for row in rows if row["verdict_ml"] == "basse_priorite_a_relire"]
    middle = [row for row in rows if row["verdict_ml"] == "a_lire"]
    high = [row for row in rows if row["verdict_ml"] == "prioriser"]
    stable = lambda row: hashlib.sha256(row["simplify_id"].encode()).hexdigest()
    chosen = [("basse_priorite", row) for row in sorted(low, key=stable)[:30]]
    chosen += [("a_lire", row) for row in sorted(middle, key=stable)[:20]]
    chosen += [("prioriser", row) for row in sorted(high, key=stable)[:20]]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        for group, row in chosen:
            writer.writerow({**row, "groupe": group})
    return {"exportees": len(chosen), "basse_priorite": min(30, len(low)),
            "a_lire": min(20, len(middle)), "prioriser": min(20, len(high))}


def import_labels(db: sqlite3.Connection, source: Path) -> dict[str, int]:
    with source.open(encoding="utf-8-sig", newline="") as file:
        header = file.readline()
        file.seek(0)
        delimiter = ";" if header.count(";") > header.count(",") else ","
        reader = csv.DictReader(file, delimiter=delimiter)
        if not {"simplify_id", "label_humain"}.issubset(reader.fieldnames or []):
            raise ValueError("Colonnes simplify_id et label_humain requises")
        rows = [(row["simplify_id"].strip(), row["label_humain"].strip()) for row in reader]
    values = [(sid, int(label)) for sid, label in rows if label]
    if any(label not in (0, 1) for _, label in values):
        raise ValueError("label_humain doit être 0 ou 1")
    if len({sid for sid, _ in values}) != len(values):
        raise ValueError("Identifiant SWElist dupliqué dans la revue")
    for sid, label in values:
        existing = db.execute(
            "SELECT label_humain FROM swelist_annonces WHERE simplify_id=?", (sid,)
        ).fetchone()
        if existing is None:
            raise ValueError(f"Offre SWElist inconnue : {sid}")
        if existing[0] is not None and existing[0] != label:
            raise ValueError(f"Étiquette déjà différente : {sid}")
    with db:
        db.executemany("UPDATE swelist_annonces SET label_humain=? WHERE simplify_id=?",
                       [(label, sid) for sid, label in values])
    return {"lues": len(rows), "etiquetees": len(values)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--export", type=Path)
    group.add_argument("--import-labels", type=Path)
    args = parser.parse_args()
    db = sqlite3.connect(args.db, timeout=30)
    try:
        result = export_review(db, args.export) if args.export else import_labels(db, args.import_labels)
        print(result)
    finally:
        db.close()


if __name__ == "__main__":
    main()
