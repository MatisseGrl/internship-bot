"""Copy the private SQLite register to Supabase without putting secrets in the repo.

Only the local register is authoritative. This program never deletes remote rows.
It stores acknowledgements in a separate SQLite file so an interrupted run resumes
at the first unacknowledged row. Replaying a batch is safe because writes are upserts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

TABLES = {
    "offres": (
        "cle",
        "entreprise",
        "identifiant",
        "titre",
        "lieu",
        "url",
        "texte",
        "categorie_note",
        "note_json",
        "score",
        "dans_snapshot",
        "vu_le",
    ),
    "swelist_annonces": (
        "simplify_id",
        "date_mail",
        "id_mail",
        "entreprise",
        "intitule",
        "lien_simplify",
        "premier_filtre",
        "raison",
        "bot_cle_candidate",
        "rapprochement",
        "label_humain",
        "score_fit",
        "verdict_ml",
        "version_modele",
        "evalue_le",
    ),
    "classement": (
        "source",
        "identifiant",
        "rang",
        "present",
        "entreprise",
        "titre",
        "lieu",
        "url",
        "base",
        "score_fit",
        "verdict_fit",
        "score_retenue",
        "eligible",
        "motifs",
        "deja_candidature",
        "doublon_du_rang",
        "version",
        "classe_le",
    ),
    "candidatures": ("cle_offre", "statut", "preuve", "modifie_le"),
    "mails": (
        "boite",
        "identifiant_message",
        "recu_le",
        "expediteur",
        "objet",
        "categorie",
        "cle_offre",
        "justification",
        "traite_le",
    ),
}
CONFLICT = {
    "offres": "cle",
    "swelist_annonces": "simplify_id",
    "classement": "source,identifiant",
    "candidatures": "cle_offre",
    "mails": "boite,identifiant_message",
}
RETRYABLE = {408, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524}


class SyncError(RuntimeError):
    pass


def encode(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def source_snapshot(path: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    """Read the local tables in one consistent SQLite snapshot."""
    uri = path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=30)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        rows: dict[str, list[dict[str, Any]]] = {}
        available = {
            row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        for table, columns in TABLES.items():
            if table in {"swelist_annonces", "classement"} and table not in available:
                continue  # Older local registers do not yet have these tables.
            query = f"SELECT {', '.join(columns)} FROM {table} ORDER BY {CONFLICT[table]}"
            rows[table] = [dict(row) for row in db.execute(query)]
        db.execute("COMMIT")
    for row in rows["offres"]:
        if row["note_json"] is not None:
            row["note_json"] = json.loads(row["note_json"])
        row["dans_snapshot"] = bool(row["dans_snapshot"])
    for row in rows.get("classement", []):
        row["motifs"] = json.loads(row["motifs"])
        for column in ("present", "eligible", "deja_candidature"):
            row[column] = bool(row[column])
    for row in rows["mails"]:
        if row["recu_le"] == "":
            row["recu_le"] = None
    expected = {table: len(items) for table, items in rows.items()}
    expected["notes"] = sum(row["note_json"] is not None for row in rows["offres"])
    expected["textes"] = sum(row["texte"] is not None for row in rows["offres"])
    expected["dans_snapshot"] = sum(row["dans_snapshot"] for row in rows["offres"])
    return rows, expected


def identity(table: str, row: dict[str, Any]) -> str:
    return json.dumps(
        [row[column] for column in CONFLICT[table].split(",")],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def digest(row: dict[str, Any]) -> str:
    return hashlib.sha256(encode(row)).hexdigest()


def open_state(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS acknowledged (
        table_name TEXT NOT NULL, row_key TEXT NOT NULL, sha256 TEXT NOT NULL,
        PRIMARY KEY(table_name, row_key))""")
    db.commit()
    return db


@contextmanager
def single_instance(path: Path):
    """OS lock: a crashed process releases it without leaving a stale lease."""
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        lock_file = lock_path.open("a+b")
    except OSError as error:
        raise SyncError("Une synchronisation est déjà en cours") from error
    with lock_file as lock:
        try:
            lock.seek(0)
            if not lock.read(1):
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise SyncError("Une synchronisation est déjà en cours") from error
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


class RestClient:
    def __init__(self, url: str, key: str, *, attempts: int = 4, timeout: int = 30):
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.path not in ("", "/"):
            raise ValueError("SUPABASE_URL doit être l'URL HTTPS du projet")
        if not key.startswith("sb_secret_"):
            raise ValueError("SUPABASE_SECRET_KEY doit commencer par sb_secret_")
        self.url = url.rstrip("/")
        self.key = key
        self.attempts = attempts
        self.timeout = timeout

    def request(
        self, method: str, path: str, *, payload: bytes | None = None, prefer: str = ""
    ) -> Any:
        headers = {"apikey": self.key, "Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if prefer:
            headers["Prefer"] = prefer
        request = urllib.request.Request(
            self.url + "/rest/v1/" + path, data=payload, headers=headers, method=method
        )
        for attempt in range(self.attempts):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return response.headers
            except urllib.error.HTTPError as error:
                # Never print the response body: it can contain private row values.
                if error.code not in RETRYABLE or attempt + 1 == self.attempts:
                    raise SyncError(
                        f"Supabase HTTP {error.code} ({method} {path.split('?')[0]})"
                    ) from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
                if attempt + 1 == self.attempts:
                    raise SyncError(
                        f"Connexion Supabase impossible ({type(error).__name__})"
                    ) from None
            time.sleep(min(8, 0.5 * 2**attempt) + random.uniform(0, 0.25))
        raise AssertionError("unreachable")

    def upsert(self, table: str, rows: list[dict[str, Any]]) -> None:
        if table == "candidatures":
            # PATCH keeps a remotely stored cv untouched. A bulk POST upsert
            # would set the omitted cv column to NULL on an existing row.
            for row in rows:
                path = "candidatures?cle_offre=eq." + urllib.parse.quote(row["cle_offre"], safe="")
                self.request(
                    "POST",
                    "candidatures?on_conflict=cle_offre",
                    payload=encode(row),
                    prefer="resolution=ignore-duplicates,return=minimal",
                )
                self.request("PATCH", path, payload=encode(row), prefer="return=minimal")
            return
        conflict = urllib.parse.quote(CONFLICT[table], safe=",")
        self.request(
            "POST",
            f"{table}?on_conflict={conflict}",
            payload=encode(rows),
            prefer="resolution=merge-duplicates,return=minimal",
        )

    @staticmethod
    def _count_header(headers: Any, table: str) -> int:
        value = headers.get("Content-Range", "")
        try:
            return int(value.rsplit("/", 1)[1])
        except (IndexError, ValueError) as error:
            raise SyncError(f"Compte Supabase indisponible pour {table}") from error

    def count(self, table: str, where: str = "") -> int:
        path = f"{table}?select={urllib.parse.quote(CONFLICT[table].split(',')[0])}{where}"
        headers = self.request("HEAD", path, prefer="count=exact")
        return self._count_header(headers, table)


def batches(items: list[tuple[str, str, dict[str, Any]]], max_bytes: int):
    batch: list[tuple[str, str, dict[str, Any]]] = []
    size = 2
    for item in items:
        row_size = len(encode(item[2])) + 1
        if batch and size + row_size > max_bytes:
            yield batch
            batch, size = [], 2
        batch.append(item)
        size += row_size
    if batch:
        yield batch


def compare_counts(client: RestClient, expected: dict[str, int]) -> dict[str, int]:
    actual = {table: client.count(table) for table in TABLES if table in expected}
    actual["notes"] = client.count("offres", "&note_json=not.is.null")
    actual["textes"] = client.count("offres", "&texte=not.is.null")
    actual["dans_snapshot"] = client.count("offres", "&dans_snapshot=eq.true")
    return {name: actual[name] for name in expected if actual[name] != expected[name]}


def sync(
    source: Path,
    state_path: Path,
    client: RestClient,
    *,
    full: bool = False,
    max_bytes: int = 200_000,
) -> dict[str, Any]:
    if max_bytes < 1024:
        raise ValueError("max_bytes doit être supérieur à 1024")
    if source.resolve() == state_path.resolve():
        raise ValueError("Le fichier d'état doit être distinct du registre")
    with single_instance(state_path), closing(open_state(state_path)) as state:
        rows, expected = source_snapshot(source)
        uploaded = {table: 0 for table in rows}
        known = {
            (table, key): sha
            for table, key, sha in state.execute(
                "SELECT table_name,row_key,sha256 FROM acknowledged"
            )
        }

        def upload(force: bool) -> None:
            for table in rows:  # Foreign keys: offers before the source and applications.
                changed = []
                for row in rows[table]:
                    key, sha = identity(table, row), digest(row)
                    if force or known.get((table, key)) != sha:
                        changed.append((key, sha, row))
                for batch in batches(changed, max_bytes):
                    client.upsert(table, [item[2] for item in batch])
                    with state:
                        state.executemany(
                            """INSERT INTO acknowledged(table_name,row_key,sha256)
                            VALUES(?,?,?) ON CONFLICT(table_name,row_key)
                            DO UPDATE SET sha256=excluded.sha256""",
                            [(table, key, sha) for key, sha, _ in batch],
                        )
                    uploaded[table] += len(batch)

        upload(full)
        mismatch = compare_counts(client, expected)
        if (
            mismatch
            and not full
            and not any(client.count(table) > expected[table] for table in rows)
        ):
            # A remote table can be truncated while local acknowledgements survive.
            # Replay once before declaring the copy inconsistent.
            upload(True)
            mismatch = compare_counts(client, expected)
        if mismatch:
            raise SyncError("Comptes Supabase divergents : " + ", ".join(sorted(mismatch)))
    return {"source": expected, "uploaded": uploaded, "counts_verified": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="Registre SQLite privé")
    parser.add_argument("--state", type=Path, help="État privé, défaut: à côté du registre")
    parser.add_argument("--full", action="store_true", help="Réécrire toutes les lignes")
    parser.add_argument("--max-bytes", type=int, default=200_000)
    args = parser.parse_args()
    state = args.state or args.db.with_name("sync_supabase.sqlite")
    try:
        client = RestClient(
            os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_SECRET_KEY", "")
        )
        result = sync(args.db, state, client, full=args.full, max_bytes=args.max_bytes)
    except (OSError, sqlite3.Error, ValueError, SyncError) as error:
        print(f"Synchronisation echouee : {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
