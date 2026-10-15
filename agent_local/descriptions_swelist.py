"""Récupère lentement la description des annonces SWElist depuis leur page Simplify.

Lecture seule : une requête GET par page publique `/p/<id>` (autorisée par robots.txt),
au plus une toutes les quelques secondes. Le lien « Apply » (`/jobs/click/`, interdit par
robots.txt) n'est jamais suivi et aucun formulaire n'est touché. Un blocage (403, 429,
vérification humaine) arrête la commande au lieu d'être contourné.

Les textes vont dans la table privée `swelist_descriptions`, séparée de `swelist_annonces`
et non copiée vers Supabase. Une relance reprend là où la précédente s'est arrêtée.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS swelist_descriptions (
    simplify_id TEXT PRIMARY KEY REFERENCES swelist_annonces(simplify_id),
    recupere_le TEXT NOT NULL,
    statut_http INTEGER,
    actif INTEGER,
    description_html TEXT,
    description_texte TEXT,
    exigences TEXT,
    missions TEXT,
    souhaitable TEXT,
    lieux TEXT,
    date_debut TEXT,
    date_fin TEXT,
    mise_a_jour TEXT,
    ats_suivi TEXT,
    erreur TEXT
);
"""
USER_AGENT = "internship-bot/0.1 (usage personnel ; lecture lente de pages publiques)"
BLOCKING = {401, 403, 407, 429, 503}
VERDICT_ORDER = {"prioriser": 0, "a_lire": 1, "basse_priorite_a_relire": 2}

Fetch = Callable[[str], tuple[int, str]]


class Blocked(RuntimeError):
    pass


class _Text(HTMLParser):
    BLOCKS = frozenset({"p", "br", "li", "div", "h1", "h2", "h3", "h4", "ul", "ol", "tr"})

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _Text()
    parser.feed(html)
    lines = (re.sub(r"\s+", " ", line).strip() for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line)


def parse_page(page: str) -> dict:
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, flags=re.DOTALL)
    if not match:
        raise ValueError("__NEXT_DATA__ absent")
    posting = json.loads(match.group(1)).get("props", {}).get("pageProps", {}).get("jobPosting")
    if not isinstance(posting, dict) or not posting.get("description"):
        raise ValueError("description absente")

    def texts(key: str) -> str:
        return json.dumps(posting.get(key) or [], ensure_ascii=False)

    return {
        "actif": None if posting.get("active") is None else int(bool(posting["active"])),
        "description_html": posting["description"],
        "description_texte": html_to_text(posting["description"]),
        "exigences": texts("requirements"),
        "missions": texts("responsibilities"),
        "souhaitable": texts("desirable"),
        "lieux": json.dumps(
            [x.get("value") for x in posting.get("locations") or [] if isinstance(x, dict)],
            ensure_ascii=False,
        ),
        "date_debut": posting.get("start_date"),
        "date_fin": posting.get("end_date"),
        "mise_a_jour": posting.get("updated_date"),
        "ats_suivi": posting.get("tracked_obj"),
    }


def http_get(url: str) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, ""


def pending(db: sqlite3.Connection) -> list[tuple[str, str]]:
    """Annonces sans description réussie, `prioriser` d'abord puis par score décroissant."""
    rows = db.execute(
        """SELECT a.simplify_id, a.lien_simplify, a.verdict_ml, a.score_fit
           FROM swelist_annonces a LEFT JOIN swelist_descriptions d USING (simplify_id)
           WHERE d.simplify_id IS NULL OR (d.description_texte IS NULL AND d.statut_http <> 404)"""
    ).fetchall()
    rows.sort(key=lambda r: (VERDICT_ORDER.get(r[2], 3), -(r[3] or 0), r[0]))
    return [(sid, url) for sid, url, _, _ in rows]


def record(db: sqlite3.Connection, sid: str, status: int | None, fields: dict, error: str) -> None:
    columns = ["simplify_id", "recupere_le", "statut_http", "erreur", *fields]
    values = [sid, datetime.now(UTC).isoformat(), status, error or None, *fields.values()]
    with db:
        db.execute(
            f"INSERT OR REPLACE INTO swelist_descriptions({','.join(columns)}) "
            f"VALUES({','.join('?' * len(columns))})",
            values,
        )


def run(
    db: sqlite3.Connection,
    limit: int | None,
    delay: float,
    fetch: Fetch = http_get,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
) -> dict[str, int]:
    db.executescript(SCHEMA)
    queue = pending(db)[:limit] if limit else pending(db)
    stats = {"a_traiter": len(queue), "ok": 0, "erreurs": 0}
    consecutive = 0
    for index, (sid, url) in enumerate(queue):
        if index:
            sleep(delay + random.uniform(0, delay / 2))
        try:
            status, page = fetch(url)
        except (OSError, TimeoutError) as error:
            status, page = None, ""
            record(db, sid, None, {}, f"reseau: {error}")
        else:
            if status in BLOCKING or "Human Verification" in page[:5000]:
                record(db, sid, status, {}, "blocage")
                raise Blocked(f"Blocage HTTP {status} sur {sid} : arrêt sans contournement")
            if status == 200:
                try:
                    record(db, sid, status, parse_page(page), "")
                    stats["ok"] += 1
                    consecutive = 0
                except ValueError as error:
                    record(db, sid, status, {}, str(error))
            else:
                record(db, sid, status, {}, f"http {status}")
        if (
            status != 200
            or db.execute(
                "SELECT description_texte IS NULL FROM swelist_descriptions WHERE simplify_id=?",
                (sid,),
            ).fetchone()[0]
        ):
            stats["erreurs"] += 1
            consecutive += 1
            if consecutive >= 5:
                raise Blocked("5 échecs consécutifs : arrêt pour vérification")
        if (index + 1) % 25 == 0:
            log(f"{index + 1}/{len(queue)} traitées, {stats['ok']} descriptions")
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--limite", type=int, help="nombre maximal de pages pour ce passage")
    parser.add_argument("--delai", type=float, default=2.5, help="secondes entre deux pages")
    args = parser.parse_args()
    if args.delai < 2:
        parser.error("--delai doit rester d'au moins 2 secondes")
    db = sqlite3.connect(args.db, timeout=60)
    try:
        print(json.dumps(run(db, args.limite, args.delai), ensure_ascii=False))
    except Blocked as error:
        print(f"ARRET : {error}")
        raise SystemExit(2) from error
    finally:
        db.close()


if __name__ == "__main__":
    main()
