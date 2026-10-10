"""Orchestration d'un run : récupération -> dédoublonnage -> filtrage -> notification -> état.

Filtre v3 (filters_v3.py) : chaque nouvelle offre tombe dans un seau.
- notify : alerte Telegram immédiate (⭐ si offre IA) ;
- review : ajoutée au résumé quotidien « à vérifier » (premier passage après 9 h, Paris) ;
- drop   : ignorée (raison loggée en --verbose).

Garanties :
- chaque entreprise est isolée : une erreur est loggée, résumée, et les autres continuent ;
- premier passage pour une entreprise = seed silencieux (aucune notification) ;
- une offre « notify » n'est marquée « vue » qu'APRÈS envoi réussi de sa notification ;
- les offres « review » et « drop » sont marquées vues immédiatement (les « review » restent
  dans l'état jusqu'à l'envoi du résumé) : modifier les filtres plus tard ne déclenche pas
  une avalanche d'anciennes offres ;
- passage au filtre v3 : les offres déjà vues ne sont jamais renotifiées une à une ; celles que
  l'ancien filtre cachait et que le v3 retient sont signalées UNE fois, dans un seul récap.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from internbot.config import AppConfig, CompanyConfig
from internbot.errors import InternbotError
from internbot.filters import JobClassifier
from internbot.filters_v3 import DROP, NOTIFY, REVIEW, Verdict
from internbot.http import HttpClient
from internbot.models import Job
from internbot.notation import Notation
from internbot.notifiers.base import Notifier
from internbot.providers import get_provider_class
from internbot.providers.base import Provider
from internbot.snapshot import (
    build_health,
    build_snapshot,
    load_snapshot,
    save_snapshot,
    snapshot_jobs,
)
from internbot.storage import StateStore

log = logging.getLogger(__name__)

FILTER_VERSION = 3
PARIS = ZoneInfo("Europe/Paris")
REVIEW_DIGEST_HOUR = 9  # résumé « à vérifier » : premier passage après 9 h (heure de Paris)


@dataclass
class CompanyResult:
    name: str
    provider: str = ""
    ok: bool = True
    fetched: int = 0
    notify: int = 0
    review: int = 0
    new_matches: int = 0
    new_reviews: int = 0
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
                    + (f", {r.new_reviews} à vérifier" if r.new_reviews else "")
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
        notation: Notation | None = None,
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
        # Verdicts de la grille de notation (notation/notes.json) : les offres écartées sont
        # retirées de current.json (/offres, --send-all) et du résumé « à vérifier ».
        self.notation = notation or Notation(None)
        self._providers: dict[str, Provider] = {}
        # Offres ouvertes qui passent les filtres, par entreprise traitée avec succès.
        self._current: dict[str, list[Job]] = {}
        self._previous: dict[str, Any] = {}  # current.json du run précédent
        self._new_reviews: list[Job] = []
        self._recap: list[Job] = []  # passage au filtre v3 (voir _migration_candidates)

    def run(self, companies: Sequence[CompanyConfig]) -> RunReport:
        report = RunReport()
        pending: list[Job] = []
        self._previous = load_snapshot(self.snapshot_path)
        for company in companies:
            if not get_provider_class(company.provider).automated:
                log.info("── %s : suivie à la main, ignorée", company.name)
                continue
            log.info("── %s (%s)", company.name, company.provider)
            result, to_notify = self._process_company(company)
            report.results.append(result)
            pending.extend(to_notify)
            if not self.dry_run:
                self.state.save()

        snapshot = build_snapshot(
            self._previous,
            self._current,
            [c.name for c in self.config.companies],
            self.now,
        )
        snapshot["health"] = build_health(
            self._previous.get("health") or {},
            self.config.companies,
            report.results,
            {name: count for name, count, _ in self.state.failing_companies()},
            self.now,
        )
        listing_sent = self.send_all and self._send_listing(snapshot, report)

        if pending:
            pending.sort(key=lambda j: not j.priority)  # offres IA (⭐) en premier
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

        self._migration_recap(companies)
        if self.dry_run and self._new_reviews:
            self.notifier.send_digest(
                f"🔎 {len(self._new_reviews)} nouvelle(s) offre(s) à vérifier "
                "(iraient dans le résumé quotidien)",
                self._new_reviews,
            )
        if not self.dry_run:
            self._failure_alerts(report)
            self._maybe_digest()
            self._maybe_review_digest()
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
        result = CompanyResult(name=company.name, provider=company.provider)
        provider = self._provider(company.provider)
        try:
            jobs = _dedupe(provider.fetch_jobs(company))
        except InternbotError as exc:
            return self._fail(company, result, str(exc)), []
        except Exception as exc:  # bug inattendu : on isole quand même l'entreprise
            log.exception("Erreur inattendue pour %s", company.name)
            return self._fail(company, result, f"{type(exc).__name__}: {exc}"), []

        result.fetched = len(jobs)
        classifier = JobClassifier(self.config.filters_for(company))
        statuses = [classifier.classify(job).status for job in jobs]
        result.notify = statuses.count(NOTIFY)
        result.review = statuses.count(REVIEW)
        log.info(
            "%s : %d offre(s) récupérée(s) (NOTIFY %d, REVIEW %d)",
            company.name,
            len(jobs),
            result.notify,
            result.review,
        )

        previously_active = self.state.active_count(company.name)
        if not jobs and previously_active:
            log.warning(
                "%s : 0 offre alors que %d étaient actives — format ou recherche modifiés ?",
                company.name,
                previously_active,
            )

        if self.force_seed or not self.state.is_seeded(company.name):
            result.seeded = True
            self._seed(company, jobs, classifier)
            self._current[company.name] = self._current_matches(provider, company, jobs, classifier)
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
        reviews: list[Job] = []
        rejected: set[str] = set()
        for job in new_jobs:
            verdict = classifier.title_verdict(job.title)
            if verdict.status != DROP:
                job = provider.enrich(company, job)
                verdict = classifier.classify(job)
            job = _with_verdict(job, verdict)
            if verdict.status == NOTIFY:
                to_notify.append(job)
                log.info(
                    "%s : NOUVELLE offre%s « %s » (%s) — %s",
                    company.name,
                    " ⭐" if job.priority else "",
                    job.title,
                    job.location,
                    verdict.reason,
                )
            elif verdict.status == REVIEW:
                reviews.append(job)
                log.info(
                    "%s : à vérifier « %s » (%s) — %s",
                    company.name,
                    job.title,
                    job.location,
                    verdict.reason,
                )
                if not self.dry_run:
                    self.state.queue_review(job)
                    self.state.mark_seen(job, notified=False)
            else:
                log.debug("%s : ignorée « %s » — %s", company.name, job.title, verdict.reason)
                rejected.add(job.job_id)
                if not self.dry_run:
                    self.state.mark_seen(job, notified=False)

        result.new_matches = len(to_notify)
        result.new_reviews = len(reviews)
        self._new_reviews.extend(reviews)
        enriched = {j.job_id: j for j in to_notify + reviews}
        current = self._current_matches(
            provider,
            company,
            [enriched.get(j.job_id, j) for j in jobs if j.job_id not in rejected],
            classifier,
        )
        self._current[company.name] = current
        if self.state.filter_version < FILTER_VERSION:
            self._recap.extend(
                self._migration_candidates(company.name, current, {j.job_id for j in new_jobs})
            )
        log.info(
            "%s : %d nouvelle(s) offre(s), dont %d correspondante(s) et %d à vérifier",
            company.name,
            len(new_jobs),
            len(to_notify),
            len(reviews),
        )
        if not self.dry_run:
            self.state.record_success(company.name)
        return result, to_notify

    def _current_matches(
        self,
        provider: Provider,
        company: CompanyConfig,
        jobs: list[Job],
        classifier: JobClassifier,
    ) -> list[Job]:
        """Offres ouvertes « notify » ou « review » (pour current.json / --send-all / /offres),
        sauf celles que la grille de notation a écartées."""
        out = []
        for job in jobs:
            if self.notation.est_ecartee(*job.key):
                continue
            if classifier.title_verdict(job.title).status == DROP:
                continue
            job = self._resolve_location(provider, company, job)
            verdict = classifier.classify(job)
            if verdict.status != DROP:
                out.append(_with_verdict(job, verdict))
        return out

    def _migration_candidates(
        self, company: str, current: list[Job], new_ids: set[str]
    ) -> list[Job]:
        """Premier run du filtre v3 : offres ouvertes, déjà vues, jamais notifiées, que l'ancien
        filtre cachait (absentes du current.json précédent, écrit avec l'ancien filtre) et que
        le v3 classe « notify ». Sans liste précédente pour l'entreprise : aucune (pas de spam)."""
        previous = (self._previous.get("companies") or {}).get(company)
        if previous is None:
            return []
        shown = {str(j.get("job_id")) for j in previous.get("jobs") or []}
        return [
            j
            for j in current
            if j.status == NOTIFY
            and j.job_id not in shown
            and j.job_id not in new_ids
            and not self.state.was_notified(company, j.job_id)
        ]

    def _resolve_location(self, provider: Provider, company: CompanyConfig, job: Job) -> Job:
        """Lieu complet d'une offre multi-lieux (Workday « 3 Locations ») : depuis l'état si déjà
        connu, sinon requête de détail (plafonnée par run) mise en cache pour les runs suivants.
        Sans cela, un filtre de lieu ne pourrait pas écarter ces offres de la liste /offres."""
        if job.location_complete:
            return job
        cached = self.state.cached_location(company.name, job.job_id)
        if cached:
            return job.with_updates(location=cached, location_complete=True)
        detailed = provider.enrich(company, job)
        if detailed.location_complete and not self.dry_run:
            self.state.cache_location(company.name, job.job_id, detailed.location)
        return detailed

    def _seed(self, company: CompanyConfig, jobs: list[Job], classifier: JobClassifier) -> None:
        matching = [j for j in jobs if classifier.classify(j).status != DROP]
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

    # -- filtre v3 : récap de migration et résumé « à vérifier » --------------------------------

    def _migration_recap(self, companies: Sequence[CompanyConfig]) -> None:
        """Envoie UNE fois, en un seul récap, les offres que l'ancien filtre cachait."""
        if self.state.filter_version < FILTER_VERSION:
            # Entreprises suivies à la main (provider « manual ») : jamais traitées par un run.
            enabled = {
                c.name
                for c in self.config.companies
                if c.enabled and get_provider_class(c.provider).automated
            }
            if not enabled <= {c.name for c in companies}:
                return  # run partiel (--company) : la migration attend un run complet
            recap = self._recap
            if not self.dry_run:
                self.state.set_recap_pending(recap)
                self.state.set_filter_version(FILTER_VERSION)
            log.info(
                "Passage au filtre v3 : %d offre(s) auparavant filtrée(s) à signaler", len(recap)
            )
        else:
            recap = self.state.recap_pending()
        if not recap:
            return
        title = f"🔁 Nouveau filtre : {len(recap)} offre(s) ouverte(s) que l'ancien filtre cachait"
        if self.notifier.send_digest(title, recap) and not self.dry_run:
            for job in recap:
                self.state.mark_seen(job, notified=True)
            self.state.clear_queue("recap_pending")

    def _maybe_review_digest(self) -> None:
        """Résumé quotidien des offres « à vérifier » : au premier passage après 9 h (Paris)."""
        queue = [j for j in self.state.review_queue() if not self.notation.est_ecartee(*j.key)]
        if not queue:
            self.state.clear_queue("review_queue")
            return
        local = self.now.astimezone(PARIS)
        today = local.date().isoformat()
        if local.hour < REVIEW_DIGEST_HOUR or self.state.last_review_digest == today:
            return
        title = f"🔎 À vérifier : {len(queue)} offre(s) ambiguë(s), à trier à la main"
        if self.notifier.send_digest(title, queue):
            self.state.clear_queue("review_queue")
            self.state.set_last_review_digest(today)

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


def _with_verdict(job: Job, verdict: Verdict) -> Job:
    return job.with_updates(status=verdict.status, reason=verdict.reason, priority=verdict.priority)


def _dedupe(jobs: list[Job]) -> list[Job]:
    seen: dict[str, Job] = {}
    for job in jobs:
        seen.setdefault(job.job_id, job)
    return list(seen.values())
