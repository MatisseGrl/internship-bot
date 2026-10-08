"""Orchestration d'un run : récupération -> dédoublonnage -> filtrage -> notification -> état.

Garanties :
- chaque entreprise est isolée : une erreur est loggée, résumée, et les autres continuent ;
- premier passage pour une entreprise = seed silencieux (aucune notification) ;
- une offre correspondante n'est marquée « vue » qu'APRÈS envoi réussi de sa notification ;
- les offres qui ne passent pas les filtres sont marquées vues immédiatement : modifier les
  filtres plus tard ne déclenche pas une avalanche d'anciennes offres.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from internbot.config import AppConfig, CompanyConfig
from internbot.errors import InternbotError
from internbot.filters import JobFilter
from internbot.http import HttpClient
from internbot.models import Job
from internbot.notifiers.base import Notifier
from internbot.providers import get_provider_class
from internbot.providers.base import Provider
from internbot.snapshot import build_snapshot, load_snapshot, save_snapshot, snapshot_jobs
from internbot.storage import StateStore

log = logging.getLogger(__name__)


@dataclass
class CompanyResult:
    name: str
    ok: bool = True
    fetched: int = 0
    new_matches: int = 0
    seeded: bool = False
    removed: int = 0
    error: str | None = None


@dataclass
class RunReport:
    results: list[CompanyResult] = field(default_factory=list)
    notified: int = 0
    pending: int = 0  # offres correspondantes dont l'envoi a échoué (réessayées au prochain run)

    @property
    def failures(self) -> list[CompanyResult]:
        return [r for r in self.results if not r.ok]

    @property
    def all_failed(self) -> bool:
        return bool(self.results) and len(self.failures) == len(self.results)

    def summary(self) -> str:
        lines = [
            f"Résumé : {len(self.results)} entreprise(s), {len(self.failures)} en échec, "
            f"{self.notified} notification(s) envoyée(s)"
            + (f", {self.pending} en attente de renvoi" if self.pending else "")
        ]
        for r in self.results:
            if not r.ok:
                lines.append(f"  ✗ {r.name} : {r.error}")
            elif r.seeded:
                lines.append(
                    f"  ● {r.name} : {r.fetched} offre(s) enregistrée(s) (seed silencieux)"
                )
            else:
                lines.append(
                    f"  ✓ {r.name} : {r.fetched} offre(s), "
                    f"{r.new_matches} nouvelle(s) correspondante(s)"
                    + (f", {r.removed} disparue(s)" if r.removed else "")
                )
        return "\n".join(lines)


class Runner:
    def __init__(
        self,
        config: AppConfig,
        state: StateStore,
        notifier: Notifier,
        http: HttpClient,
        *,
        dry_run: bool = False,
        force_seed: bool = False,
        send_all: bool = False,
        snapshot_path: Path | None = None,
        now: datetime | None = None,
    ) -> None:
        self.config = config
        self.state = state
        self.notifier = notifier
        self.http = http
        self.dry_run = dry_run
        self.force_seed = force_seed
        self.now = now or datetime.now(UTC)
        self.send_all = send_all
        self.snapshot_path = snapshot_path
        self._providers: dict[str, Provider] = {}
        # Offres ouvertes qui passent les filtres, par entreprise traitée avec succès.
        self._current: dict[str, list[Job]] = {}

    def run(self, companies: Sequence[CompanyConfig]) -> RunReport:
        report = RunReport()
        pending: list[Job] = []
        for company in companies:
            log.info("── %s (%s)", company.name, company.provider)
            result, to_notify = self._process_company(company)
            report.results.append(result)
            pending.extend(to_notify)
            if not self.dry_run:
                self.state.save()

        snapshot = build_snapshot(
            load_snapshot(self.snapshot_path),
            self._current,
            [c.name for c in self.config.companies],
            self.now,
        )
        listing_sent = self.send_all and self._send_listing(snapshot, report)

        if pending:
            # Avec --send-all, les nouvelles offres figurent déjà dans la liste envoyée.
            delivered = list(pending) if listing_sent else self.notifier.notify(pending)
            report.notified = len(delivered)
            report.pending = len(pending) - len(delivered)
            if not self.dry_run:
                for job in delivered:
                    self.state.mark_seen(job, notified=True)
            if report.pending:
                log.warning(
                    "%d notification(s) non envoyée(s) : elles seront retentées au prochain run",
                    report.pending,
                )

        if not self.dry_run:
            self._failure_alerts(report)
            self._maybe_digest()
            self.state.prune_removed()
            self.state.save()
            if self.snapshot_path is not None:
                save_snapshot(self.snapshot_path, snapshot)
        return report

    def _send_listing(self, snapshot: dict[str, object], report: RunReport) -> bool:
        jobs = snapshot_jobs(snapshot)
        subtitle = f"mise à jour {self.now:%d/%m %H:%M} UTC"
        if report.failures:
            subtitle += " — en échec, liste du dernier succès : " + ", ".join(
                r.name for r in report.failures
            )
        ok = self.notifier.send_listing(jobs, subtitle=subtitle)
        log.info("Liste complète (%d offres) %s.", len(jobs), "envoyée" if ok else "NON envoyée")
        return ok

    # -- par entreprise -------------------------------------------------------------------------

    def _provider(self, name: str) -> Provider:
        if name not in self._providers:
            self._providers[name] = get_provider_class(name)(self.http)
        return self._providers[name]

    def _process_company(self, company: CompanyConfig) -> tuple[CompanyResult, list[Job]]:
        result = CompanyResult(name=company.name)
        provider = self._provider(company.provider)
        try:
            jobs = _dedupe(provider.fetch_jobs(company))
        except InternbotError as exc:
            return self._fail(company, result, str(exc)), []
        except Exception as exc:  # bug inattendu : on isole quand même l'entreprise
            log.exception("Erreur inattendue pour %s", company.name)
            return self._fail(company, result, f"{type(exc).__name__}: {exc}"), []

        result.fetched = len(jobs)
        log.info("%s : %d offre(s) récupérée(s)", company.name, len(jobs))
        job_filter = JobFilter(self.config.filters_for(company))

        previously_active = self.state.active_count(company.name)
        if not jobs and previously_active:
            log.warning(
                "%s : 0 offre alors que %d étaient actives — format ou recherche modifiés ?",
                company.name,
                previously_active,
            )

        if self.force_seed or not self.state.is_seeded(company.name):
            result.seeded = True
            self._current[company.name] = [j for j in jobs if job_filter.matches(j)]
            self._seed(company, jobs, job_filter)
            if not self.dry_run:
                self.state.record_success(company.name)
            return result, []

        if not self.dry_run:
            removed, returned = self.state.sync_presence(company.name, (j.job_id for j in jobs))
            result.removed = len(removed)
            if removed and self.config.alerts.log_removed:
                for job_id in removed:
                    log.info(
                        "%s : offre disparue %s (%s)",
                        company.name,
                        job_id,
                        self.state.title_of(company.name, job_id),
                    )
            if returned:
                log.info(
                    "%s : %d offre(s) réapparue(s) (non re-notifiées)", company.name, len(returned)
                )

        new_jobs = [j for j in jobs if not self.state.is_known(company.name, j.job_id)]
        to_notify: list[Job] = []
        rejected: set[str] = set()
        for job in new_jobs:
            reason = job_filter.title_reject_reason(job.title)
            if reason is None:
                job = provider.enrich(company, job)
                reason = job_filter.location_reject_reason(job)
            if reason is None:
                to_notify.append(job)
                log.info("%s : NOUVELLE offre « %s » (%s)", company.name, job.title, job.location)
            else:
                log.debug("%s : ignorée « %s » — %s", company.name, job.title, reason)
                rejected.add(job.job_id)
                if not self.dry_run:
                    self.state.mark_seen(job, notified=False)

        result.new_matches = len(to_notify)
        enriched = {j.job_id: j for j in to_notify}
        self._current[company.name] = [
            enriched.get(j.job_id, j)
            for j in jobs
            if j.job_id not in rejected and (j.job_id in enriched or job_filter.matches(j))
        ]
        log.info(
            "%s : %d nouvelle(s) offre(s), dont %d correspondante(s)",
            company.name,
            len(new_jobs),
            len(to_notify),
        )
        if not self.dry_run:
            self.state.record_success(company.name)
        return result, to_notify

    def _seed(self, company: CompanyConfig, jobs: list[Job], job_filter: JobFilter) -> None:
        matching = [j for j in jobs if job_filter.matches(j)]
        if self.dry_run:
            log.info(
                "%s : [dry-run] seed silencieux de %d offre(s) (aucune notification). "
                "%d correspondent actuellement aux filtres :",
                company.name,
                len(jobs),
                len(matching),
            )
            for job in matching:
                log.info("    · %s — %s — %s", job.title, job.location or "?", job.url)
            return
        if not jobs:
            log.warning(
                "%s : 0 offre au premier passage — identifiant (board/tenant…) correct ?",
                company.name,
            )
        added = self.state.seed(company.name, jobs)
        log.info(
            "%s : seed silencieux, %d offre(s) enregistrée(s) sans notification "
            "(%d correspondent aux filtres). Seules les futures offres seront notifiées.",
            company.name,
            added,
            len(matching),
        )

    def _fail(self, company: CompanyConfig, result: CompanyResult, error: str) -> CompanyResult:
        result.ok = False
        result.error = error
        log.error("%s : ÉCHEC — %s", company.name, error)
        if not self.dry_run:
            self.state.record_failure(company.name, error)
        return result

    # -- alertes et récapitulatif ---------------------------------------------------------------

    def _failure_alerts(self, report: RunReport) -> None:
        threshold = self.config.alerts.failure_threshold
        if threshold <= 0:
            return
        for name, count, error in self.state.failing_companies():
            # Une seule alerte, au moment où le seuil est franchi (pas de spam à chaque run).
            if count == threshold and any(r.name == name and not r.ok for r in report.results):
                self.notifier.send_text(
                    f"⚠️ internbot : « {name} » échoue depuis {count} runs d'affilée.\n"
                    f"Dernière erreur : {error}\n"
                    "Le format du site a peut-être changé : vérifiez la config "
                    "(README › Dépannage)."
                )

    def _maybe_digest(self) -> None:
        cfg = self.config.digest
        if not cfg.enabled:
            return
        last = self.state.last_digest
        if last is None:
            self.state.set_last_digest(self.now)
            return
        if self.now - last < timedelta(days=cfg.every_days):
            return
        notified = self.state.notified_since(last)
        failing = self.state.failing_companies()
        lines = [f"📊 Récapitulatif internbot ({cfg.every_days} derniers jours)"]
        lines.append(f"{len(notified)} offre(s) notifiée(s).")
        for company, title in notified[:30]:
            lines.append(f"• {company} — {title}")
        if len(notified) > 30:
            lines.append(f"… et {len(notified) - 30} autre(s)")
        lines.append(f"{len(self.config.companies)} entreprise(s) surveillée(s).")
        if failing:
            lines.append("En échec : " + ", ".join(f"{n} ({c}×)" for n, c, _ in failing))
        if self.notifier.send_text("\n".join(lines)):
            self.state.set_last_digest(self.now)


def _dedupe(jobs: list[Job]) -> list[Job]:
    seen: dict[str, Job] = {}
    for job in jobs:
        seen.setdefault(job.job_id, job)
    return list(seen.values())
