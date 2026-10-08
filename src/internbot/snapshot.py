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

Clé `health` (santé de chaque entreprise configurée, pour `--status` et `/status`) :
    "health": {"Adobe": {"provider": "workday", "status": "ok", "last_run": "...",
                         "last_success": "...", "fetched": 120, "notify": 4, "review": 2,
                         "error": null, "failures": 0}}
`status` vaut ok | error | manual | disabled | pending (jamais encore interrogée).
Elle vit ici plutôt que dans state.json : current.json est déjà réécrit à chaque run, alors que
state.json ne doit changer que lorsqu'une offre apparaît ou disparaît.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from internbot.models import Job

if TYPE_CHECKING:
    from internbot.config import CompanyConfig
    from internbot.runner import CompanyResult

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


def build_health(
    previous: Mapping[str, Any],
    companies: Iterable[CompanyConfig],
    results: Iterable[CompanyResult],
    failures: Mapping[str, int],
    now: datetime,
) -> dict[str, Any]:
    """Santé de chaque entreprise configurée. Une entreprise non traitée pendant ce run
    (`--company`, désactivée…) garde ses derniers chiffres connus."""
    from internbot.providers import get_provider_class

    ts = now.replace(microsecond=0).isoformat()
    by_name = {r.name: r for r in results}
    out: dict[str, Any] = {}
    for company in companies:
        prev = dict(previous.get(company.name) or {})
        entry: dict[str, Any] = {
            "provider": company.provider,
            "status": prev.get("status", "pending"),
            "last_run": prev.get("last_run"),
            "last_success": prev.get("last_success"),
            "fetched": prev.get("fetched"),
            "notify": prev.get("notify"),
            "review": prev.get("review"),
            "error": prev.get("error"),
            "failures": failures.get(company.name, 0),
        }
        result = by_name.get(company.name)
        if not get_provider_class(company.provider).automated:
            entry.update(
                status="manual",
                error=None,
                reason=company.opt("reason"),
                careers_url=company.opt("careers_url"),
            )
        elif result is not None:
            entry["last_run"] = ts
            if result.ok:
                entry.update(
                    status="ok",
                    last_success=ts,
                    fetched=result.fetched,
                    notify=result.notify,
                    review=result.review,
                    error=None,
                )
            else:
                entry.update(status="error", error=result.error)
        elif not company.enabled:
            entry["status"] = "disabled"
        elif entry["status"] in ("manual", "disabled"):
            entry["status"] = "pending"  # réactivée : pas encore interrogée
        out[company.name] = entry
    return out


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
