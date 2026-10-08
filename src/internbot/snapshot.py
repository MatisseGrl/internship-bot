"""Liste des offres ACTUELLEMENT ouvertes qui passent les filtres (`current.json`).

Réécrite à chaque run (à côté de state.json, sur la branche `state`). Elle sert :
- à la commande Telegram `/offres` (lue par le relais Cloudflare, réponse instantanée) ;
- à `--send-all` (envoi de la liste complète sur Telegram).

Format :
    {
      "version": 1,
      "updated_at": "2026-10-08T19:03:13+00:00",
      "companies": {
        "Adobe": {"updated_at": "...", "jobs": [{"title": ..., "location": ..., "url": ...,
                                                  "posted_at": ..., "job_id": ...}]}
      }
    }

Si une entreprise échoue pendant un run, son entrée précédente est conservée (avec son
`updated_at` d'origine) : la liste ne se vide pas à cause d'une panne passagère.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from internbot.models import Job

log = logging.getLogger(__name__)

SNAPSHOT_VERSION = 1


def job_to_dict(job: Job) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "title": job.title,
        "location": job.location,
        "url": job.url,
        "posted_at": job.posted_at,
    }


def job_from_dict(company: str, data: Mapping[str, Any]) -> Job:
    return Job(
        company=company,
        job_id=str(data["job_id"]),
        title=str(data["title"]),
        url=str(data["url"]),
        source="snapshot",
        location=str(data.get("location") or ""),
        posted_at=data.get("posted_at"),
    )


def load_snapshot(path: Path | None) -> dict[str, Any]:
    empty: dict[str, Any] = {"version": SNAPSHOT_VERSION, "updated_at": None, "companies": {}}
    if path is None or not path.exists():
        return empty
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("%s illisible : la liste des offres sera reconstruite.", path)
        return empty
    if not isinstance(data, dict) or data.get("version") != SNAPSHOT_VERSION:
        return empty
    return data


def build_snapshot(
    previous: Mapping[str, Any],
    current: Mapping[str, list[Job]],
    companies: Iterable[str],
    now: datetime,
) -> dict[str, Any]:
    """`current` : entreprises traitées avec succès ; les autres gardent leur entrée précédente.
    Les entreprises retirées de la config disparaissent de la liste."""
    ts = now.replace(microsecond=0).isoformat()
    prev_companies = previous.get("companies") or {}
    out: dict[str, Any] = {}
    for name in companies:
        if name in current:
            jobs = sorted(current[name], key=lambda j: (j.title.casefold(), j.job_id))
            out[name] = {"updated_at": ts, "jobs": [job_to_dict(j) for j in jobs]}
        elif name in prev_companies:
            out[name] = prev_companies[name]
    return {"version": SNAPSHOT_VERSION, "updated_at": ts, "companies": out}


def snapshot_jobs(snapshot: Mapping[str, Any]) -> list[Job]:
    jobs = []
    for company, entry in sorted((snapshot.get("companies") or {}).items()):
        for item in entry.get("jobs") or []:
            jobs.append(job_from_dict(company, item))
    return jobs


def save_snapshot(path: Path, snapshot: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snapshot, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(prefix=".current-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(payload)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
