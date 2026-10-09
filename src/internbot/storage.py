"""État persistant des offres déjà vues, dans un fichier JSON trié (diffs git lisibles).

Format (version 1) :

    {
      "version": 1,
      "meta": {
        "last_digest": "2026-10-08T12:00:00+00:00",
        "filter_version": 3,                  # absent = ancien filtre (avant le v3)
        "review_queue": [{"company": ..., "job_id": ..., "title": ..., "reason": ...}],
        "last_review_digest": "2026-10-09",   # jour (Paris) du dernier résumé « à vérifier »
        "recap_pending": [...]                # récap de migration v3 pas encore envoyé
      },
      "companies": {
        "Salesforce": {
          "seeded_at": "...",
          "consecutive_failures": 0,
          "last_error": null,
          "jobs": {
            "JR340771": {"title": "...", "first_seen": "...", "notified_at": "..."},
            "JR123456": {"title": "...", "first_seen": "...", "removed_at": "..."}
          }
        }
      }
    }

On n'écrit volontairement aucune donnée qui change à chaque run (pas de « last_seen ») :
le fichier ne change que lorsqu'une offre apparaît/disparaît ou qu'une source échoue.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from internbot.models import Job

log = logging.getLogger(__name__)

STATE_VERSION = 1


def _utcnow() -> datetime:
    return datetime.now(UTC)


class StateStore:
    def __init__(
        self,
        path: Path | None,
        data: dict[str, Any] | None = None,
        *,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        self.path = path
        self._now = now
        self.data: dict[str, Any] = data or {"version": STATE_VERSION, "meta": {}, "companies": {}}
        self.data.setdefault("meta", {})
        self.data.setdefault("companies", {})
        self.dirty = False

    # -- chargement / sauvegarde ---------------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path, *, now: Callable[[], datetime] = _utcnow) -> StateStore:
        path = Path(path)
        if not path.exists():
            log.info("Aucun état existant (%s) : premier lancement.", path)
            return cls(path, now=now)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Fichier d'état corrompu ({path}) : {exc}. Corrigez-le ou supprimez-le "
                "(les entreprises seront alors re-seedées silencieusement)."
            ) from None
        if not isinstance(data, dict) or data.get("version") != STATE_VERSION:
            raise RuntimeError(f"Version de fichier d'état non supportée dans {path}")
        return cls(path, data, now=now)

    def save(self, *, force: bool = False) -> bool:
        """Écriture atomique (fichier temporaire + rename). Ne fait rien si rien n'a changé."""
        if self.path is None or not (self.dirty or force):
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        fd, tmp = tempfile.mkstemp(prefix=".state-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(payload)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        self.dirty = False
        return True

    # -- accès ---------------------------------------------------------------------------------

    def _company(self, company: str) -> dict[str, Any]:
        companies: dict[str, Any] = self.data["companies"]
        if company not in companies:
            companies[company] = {
                "seeded_at": None,
                "consecutive_failures": 0,
                "last_error": None,
                "jobs": {},
            }
            self.dirty = True
        entry: dict[str, Any] = companies[company]
        return entry

    def _jobs(self, company: str) -> dict[str, dict[str, Any]]:
        jobs: dict[str, dict[str, Any]] = self._company(company)["jobs"]
        return jobs

    def _ts(self) -> str:
        return self._now().replace(microsecond=0).isoformat()

    def is_seeded(self, company: str) -> bool:
        entry = self.data["companies"].get(company)
        return bool(entry and entry.get("seeded_at"))

    def is_known(self, company: str, job_id: str) -> bool:
        entry = self.data["companies"].get(company)
        return bool(entry and job_id in entry["jobs"])

    def known_ids(self, company: str) -> set[str]:
        entry = self.data["companies"].get(company)
        return set(entry["jobs"]) if entry else set()

    def active_count(self, company: str) -> int:
        entry = self.data["companies"].get(company)
        if not entry:
            return 0
        return sum(1 for rec in entry["jobs"].values() if "removed_at" not in rec)

    # -- mutations -----------------------------------------------------------------------------

    def seed(self, company: str, jobs: Iterable[Job]) -> int:
        """Enregistre les offres existantes SANS notification. Retourne le nombre d'ajouts."""
        added = 0
        for job in jobs:
            if not self.is_known(company, job.job_id):
                self._jobs(company)[job.job_id] = {"title": job.title, "first_seen": self._ts()}
                added += 1
        self._company(company)["seeded_at"] = self._ts()
        self.dirty = True
        return added

    def mark_seen(self, job: Job, *, notified: bool) -> None:
        """À appeler pour une offre notifiée APRÈS envoi réussi, ou pour une offre filtrée."""
        jobs = self._jobs(job.company)
        rec = jobs.setdefault(job.job_id, {"title": job.title, "first_seen": self._ts()})
        rec.pop("removed_at", None)
        if notified:
            rec["notified_at"] = self._ts()
        self.dirty = True

    def sync_presence(
        self, company: str, current_ids: Iterable[str]
    ) -> tuple[list[str], list[str]]:
        """Marque les offres disparues / réapparues. Retourne (disparues, réapparues).

        Les offres disparues sont conservées (avec `removed_at`) : si elles réapparaissent
        (ex: bug de pagination côté site), elles ne seront pas re-notifiées.
        """
        current = set(current_ids)
        removed, returned = [], []
        for job_id, rec in self._jobs(company).items():
            if job_id in current:
                if "removed_at" in rec:
                    del rec["removed_at"]
                    returned.append(job_id)
            elif "removed_at" not in rec:
                rec["removed_at"] = self._ts()
                removed.append(job_id)
        if removed or returned:
            self.dirty = True
        return sorted(removed), sorted(returned)

    def cached_location(self, company: str, job_id: str) -> str | None:
        """Lieu complet déjà récupéré (ex: détail Workday d'une offre « 3 Locations »)."""
        entry = self.data["companies"].get(company)
        rec = entry["jobs"].get(job_id) if entry else None
        return str(rec["location"]) if rec and rec.get("location") else None

    def cache_location(self, company: str, job_id: str, location: str) -> None:
        rec = self._jobs(company).get(job_id)
        if rec is not None and location and rec.get("location") != location:
            rec["location"] = location
            self.dirty = True

    def title_of(self, company: str, job_id: str) -> str:
        rec = self._jobs(company).get(job_id, {})
        return str(rec.get("title", job_id))

    def record_success(self, company: str) -> None:
        entry = self._company(company)
        if entry["consecutive_failures"] or entry["last_error"]:
            entry["consecutive_failures"] = 0
            entry["last_error"] = None
            self.dirty = True

    def record_failure(self, company: str, error: str) -> int:
        entry = self._company(company)
        entry["consecutive_failures"] = int(entry["consecutive_failures"]) + 1
        entry["last_error"] = error[:500]
        self.dirty = True
        return int(entry["consecutive_failures"])

    def prune_removed(self, older_than_days: int = 180) -> int:
        cutoff = self._now() - timedelta(days=older_than_days)
        pruned = 0
        for entry in self.data["companies"].values():
            for job_id in list(entry["jobs"]):
                removed_at = entry["jobs"][job_id].get("removed_at")
                if removed_at and datetime.fromisoformat(removed_at) < cutoff:
                    del entry["jobs"][job_id]
                    pruned += 1
        if pruned:
            self.dirty = True
        return pruned

    # -- récapitulatif -------------------------------------------------------------------------

    @property
    def last_digest(self) -> datetime | None:
        value = self.data["meta"].get("last_digest")
        return datetime.fromisoformat(value) if value else None

    def set_last_digest(self, when: datetime) -> None:
        self.data["meta"]["last_digest"] = when.replace(microsecond=0).isoformat()
        self.dirty = True

    # -- filtre v3 : résumé « à vérifier » et récap de migration ------------------------------

    def was_notified(self, company: str, job_id: str) -> bool:
        entry = self.data["companies"].get(company)
        rec = entry["jobs"].get(job_id) if entry else None
        return bool(rec and rec.get("notified_at"))

    @property
    def filter_version(self) -> int:
        return int(self.data["meta"].get("filter_version", 1))

    def set_filter_version(self, version: int) -> None:
        self.data["meta"]["filter_version"] = version
        self.dirty = True

    def queue_review(self, job: Job) -> None:
        """Ajoute une offre « à vérifier » au prochain résumé quotidien."""
        self._queue("review_queue", [job])

    def review_queue(self) -> list[Job]:
        return self._jobs_in("review_queue")

    def set_recap_pending(self, jobs: Iterable[Job]) -> None:
        """Offres que l'ancien filtre cachait et que le v3 retient (récap unique)."""
        self.data["meta"]["recap_pending"] = []
        self._queue("recap_pending", jobs)
        if not self.data["meta"]["recap_pending"]:
            self.clear_queue("recap_pending")

    def recap_pending(self) -> list[Job]:
        return self._jobs_in("recap_pending")

    def clear_queue(self, name: str) -> None:
        if self.data["meta"].pop(name, None) is not None:
            self.dirty = True

    @property
    def last_review_digest(self) -> str | None:
        """Date (heure de Paris, AAAA-MM-JJ) du dernier résumé « à vérifier » envoyé."""
        value = self.data["meta"].get("last_review_digest")
        return str(value) if value else None

    def set_last_review_digest(self, day: str) -> None:
        self.data["meta"]["last_review_digest"] = day
        self.dirty = True

    def _queue(self, name: str, jobs: Iterable[Job]) -> None:
        queue: list[dict[str, Any]] = self.data["meta"].setdefault(name, [])
        keys = {(r["company"], r["job_id"]) for r in queue}
        for job in jobs:
            if job.key not in keys:
                keys.add(job.key)
                queue.append(
                    {
                        "company": job.company,
                        "job_id": job.job_id,
                        "title": job.title,
                        "location": job.location,
                        "url": job.url,
                        "status": job.status,
                        "reason": job.reason,
                        "priority": job.priority,
                    }
                )
        self.dirty = True

    def _jobs_in(self, name: str) -> list[Job]:
        return [
            Job(
                company=str(r["company"]),
                job_id=str(r["job_id"]),
                title=str(r["title"]),
                url=str(r["url"]),
                source="state",
                location=str(r.get("location") or ""),
                status=str(r.get("status") or "notify"),
                reason=str(r.get("reason") or ""),
                priority=bool(r.get("priority")),
            )
            for r in self.data["meta"].get(name) or []
        ]

    def notified_since(self, since: datetime) -> list[tuple[str, str]]:
        out = []
        for company, entry in sorted(self.data["companies"].items()):
            for rec in entry["jobs"].values():
                notified_at = rec.get("notified_at")
                if notified_at and datetime.fromisoformat(notified_at) >= since:
                    out.append((company, str(rec.get("title", ""))))
        return out

    def failing_companies(self) -> list[tuple[str, int, str]]:
        return [
            (name, int(e["consecutive_failures"]), str(e.get("last_error") or ""))
            for name, e in sorted(self.data["companies"].items())
            if e.get("consecutive_failures")
        ]
