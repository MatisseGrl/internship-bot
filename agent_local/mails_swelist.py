"""Lit les alertes SWElist par IMAP et les range dans l'inventaire puis le registre, sans IA.

Connexion IMAP à Gmail en lecture seule (`readonly`) : aucun mail n'est marqué lu, déplacé
ou supprimé. Le compte et le mot de passe d'application Google viennent des variables
d'environnement `SWELIST_IMAP_USER` et `SWELIST_IMAP_PASSWORD` ; aucun secret n'est écrit.
Chaque mail passe par `ingest_swelist` (contrôle du nombre d'annonces, dédoublonnage par lien)
puis l'inventaire est importé dans `swelist_annonces` par `import_swelist`. Un mail illisible
est signalé et n'empêche pas les autres.
"""

from __future__ import annotations

import argparse
import email
import imaplib
import json
import os
import re
import sqlite3
from contextlib import suppress
from datetime import date, timedelta
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime
from pathlib import Path

from import_swelist import importer
from ingest_swelist import ingest

EXPEDITEUR = "noreply@swelist.com"
HOTE = "imap.gmail.com"


def _texte(valeur: str | None) -> str:
    return str(make_header(decode_header(valeur))) if valeur else ""


def message_depuis_brut(brut: bytes, gmail_id: str) -> dict:
    """Mail brut RFC 822 → objet attendu par `ingest_swelist.ingest`."""
    mail: Message = email.message_from_bytes(brut)
    html = ""
    for partie in mail.walk() if mail.is_multipart() else [mail]:
        if partie.get_content_type() == "text/html":
            charset = partie.get_content_charset() or "utf-8"
            html = partie.get_payload(decode=True).decode(charset, "replace")
            break
    return {
        "id": gmail_id,
        "date": parsedate_to_datetime(mail["Date"]).date().isoformat(),
        "subject": _texte(mail["Subject"]),
        "html": html,
    }


def date_depart(inventaire: Path, marge_jours: int = 2) -> date:
    """Dernier mail déjà inventorié, moins une marge ; 60 jours en arrière à défaut."""
    dates = []
    if inventaire.exists():
        with inventaire.open(encoding="utf-8-sig") as fichier:
            dates = re.findall(r'^"?(\d{4}-\d{2}-\d{2})', fichier.read(), flags=re.M)
    dernier = max((date.fromisoformat(d) for d in dates), default=None)
    return (dernier - timedelta(days=marge_jours)) if dernier else date.today() - timedelta(60)


def lire_imap(utilisateur: str, mot_de_passe: str, depuis: date) -> list[dict]:
    imap = imaplib.IMAP4_SSL(HOTE)
    try:
        imap.login(utilisateur, mot_de_passe)
        imap.select('"[Gmail]/All Mail"' if _a_tous_les_messages(imap) else "INBOX", readonly=True)
        critere = f'(FROM "{EXPEDITEUR}" SINCE {depuis.strftime("%d-%b-%Y")})'
        statut, donnees = imap.uid("SEARCH", None, critere)
        if statut != "OK":
            raise RuntimeError("Recherche IMAP refusée")
        messages = []
        for uid in donnees[0].split():
            statut, partie = imap.uid("FETCH", uid, "(X-GM-MSGID BODY.PEEK[])")
            if statut != "OK" or not partie or not isinstance(partie[0], tuple):
                continue
            entete, brut = partie[0]
            trouve = re.search(rb"X-GM-MSGID (\d+)", entete)
            # Même format que l'inventaire existant : identifiant Gmail en hexadécimal.
            gmail_id = format(int(trouve.group(1)), "x") if trouve else uid.decode()
            messages.append(message_depuis_brut(brut, gmail_id))
        return messages
    finally:
        with suppress(imaplib.IMAP4.error, OSError):
            imap.logout()


def _a_tous_les_messages(imap: imaplib.IMAP4_SSL) -> bool:
    statut, dossiers = imap.list()
    return statut == "OK" and any(b"\\All" in ligne for ligne in dossiers or [])


def traiter(messages: list[dict], inventaire: Path, db_path: Path) -> dict:
    resultat = {"mails_lus": len(messages), "annonces_ajoutees": 0, "mails_en_erreur": []}
    for message in sorted(messages, key=lambda m: (m["date"], m["id"])):
        try:
            compte = ingest([message], inventaire)
        except (ValueError, KeyError) as erreur:
            resultat["mails_en_erreur"].append({"id": message["id"], "erreur": str(erreur)})
            continue
        resultat["annonces_ajoutees"] += compte["annonces_ajoutees"]
    if inventaire.exists():
        db = sqlite3.connect(db_path, timeout=60)
        try:
            resultat["import"] = importer(db, inventaire)
        finally:
            db.close()
    return resultat


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--depuis", type=date.fromisoformat, help="date AAAA-MM-JJ (option)")
    args = parser.parse_args()
    utilisateur = os.environ.get("SWELIST_IMAP_USER", "")
    mot_de_passe = os.environ.get("SWELIST_IMAP_PASSWORD", "")
    if not utilisateur or not mot_de_passe:
        raise SystemExit("SWELIST_IMAP_USER et SWELIST_IMAP_PASSWORD doivent être définis")
    depuis = args.depuis or date_depart(args.inventory)
    messages = lire_imap(utilisateur, mot_de_passe, depuis)
    print(
        json.dumps(
            {"depuis": depuis.isoformat(), **traiter(messages, args.inventory, args.db)},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
