"""Passage quotidien sans IA : nouvelles offres, textes, éligibilité, classement, Supabase.

Étapes, chacune reprise là où elle s'est arrêtée si on relance :
1. alertes SWElist déjà extraites en JSON (`--mails-json`, optionnel) → inventaire → registre ;
2. dernier état du bot lu sur GitHub (branches `state` et `main`) → `offres` du registre ;
3. texte des offres du bot sans note ni texte (`python -m internbot --exporter-textes`) ;
4. description des annonces SWElist sans texte (pages publiques Simplify) ;
5. classement complet (`tri_texte.classer`, modèles figés, aucun réentraînement) ;
6. copie vers Supabase par le script de synchronisation existant (`--synchro`).

Aucune candidature n'est envoyée et aucun formulaire n'est touché.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import descriptions_swelist
import textes_bot
import tri_texte
from mails_swelist import traiter
from suivi_candidatures import synchroniser

TEXTE_MINIMUM = 300


def _git_show(repo: Path, objet: str, cible: Path) -> None:
    contenu = subprocess.run(
        ["git", "-C", str(repo), "show", objet], check=True, capture_output=True
    ).stdout
    cible.write_bytes(contenu)


def etat_du_bot(repo: Path, travail: Path) -> tuple[Path, Path, Path]:
    subprocess.run(["git", "-C", str(repo), "fetch", "-q", "origin", "state", "main"], check=True)
    etat = travail / ".state"
    etat.mkdir(parents=True, exist_ok=True)
    for nom in ("state.json", "current.json"):
        _git_show(repo, f"origin/state:{nom}", etat / nom)
    _git_show(repo, "origin/main:notation/notes.json", travail / "notes.json")
    return etat / "state.json", etat / "current.json", travail / "notes.json"


def textes_manquants(db: sqlite3.Connection, selection: Path) -> int:
    lignes = db.execute(
        """SELECT entreprise, identifiant FROM offres
           WHERE note_json IS NULL AND dans_snapshot=1 AND COALESCE(length(texte), 0) < ?""",
        (TEXTE_MINIMUM,),
    ).fetchall()
    with selection.open("w", encoding="utf-8") as fichier:
        for entreprise, identifiant in lignes:
            fichier.write(json.dumps({"company": entreprise, "job_id": identifiant}) + "\n")
    return len(lignes)


def run(args: argparse.Namespace) -> dict:
    travail = args.travail
    travail.mkdir(parents=True, exist_ok=True)
    resume: dict = {"debut": datetime.now(UTC).isoformat()}

    if args.mails_json and args.mails_json.exists():
        messages = json.loads(args.mails_json.read_text(encoding="utf-8"))
        resume["mails"] = traiter(messages, args.inventory, args.db)

    state, current, notes = etat_du_bot(args.repo, travail)
    db = sqlite3.connect(args.db, timeout=60)
    try:
        resume["bot"] = synchroniser(
            db,
            json.loads(notes.read_text(encoding="utf-8-sig")),
            [],
            json.loads(current.read_text(encoding="utf-8-sig")),
        )
        selection = travail / "selection_textes.jsonl"
        resume["bot_textes_a_lire"] = textes_manquants(db, selection)
    finally:
        db.close()

    sortie_textes = travail / "textes_bot.jsonl"  # reprise : le bot saute ce qui est déjà lu
    if resume["bot_textes_a_lire"]:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "internbot",
                "--exporter-textes",
                str(selection),
                "--sortie",
                str(sortie_textes),
                "--state",
                str(state),
            ],
            check=True,
        )
    db = sqlite3.connect(args.db, timeout=60)
    try:
        if sortie_textes.exists():
            resume["bot_textes"] = textes_bot.importer(db, sortie_textes)
        try:
            resume["descriptions_swelist"] = descriptions_swelist.run(db, None, args.delai)
        except descriptions_swelist.Blocked as arret:
            resume["descriptions_swelist"] = {"arret": str(arret)}
    finally:
        db.close()

    resume["classement"] = tri_texte.classer(
        args.db, args.modele_texte, args.modele_titre, args.sortie, cache=args.cache
    )
    if args.synchro:
        fin = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(args.synchro),
            ],
            check=False,
        )
        resume["synchro_supabase_code"] = fin.returncode
    resume["fin"] = datetime.now(UTC).isoformat()
    return resume


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True, help="checkout Git du bot")
    parser.add_argument("--travail", type=Path, required=True, help="dossier privé de travail")
    parser.add_argument("--modele-texte", type=Path, required=True)
    parser.add_argument("--modele-titre", type=Path, required=True)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--sortie", type=Path, required=True, help="CSV du classement")
    parser.add_argument("--mails-json", type=Path)
    parser.add_argument("--synchro", type=Path, help="script PowerShell de copie vers Supabase")
    parser.add_argument("--delai", type=float, default=2.5)
    resume = run(parser.parse_args())
    print(json.dumps(resume, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
