"""Workday (myworkdayjobs.com) — Salesforce, Nvidia, Adobe, etc.

Endpoint NON officiel, celui qu'utilise le site carrières lui-même :

    POST https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
    {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "intern"}

Particularités constatées :
- `limit` est plafonné à 20 côté Workday ;
- `total` n'est fiable que sur la PREMIÈRE page (les suivantes renvoient souvent 0) ;
- `locationsText` vaut parfois « 8 Locations » : on complète alors via l'endpoint de détail
  `GET .../wday/cxs/{tenant}/{site}{externalPath}` (uniquement pour les offres candidates) ;
- `searchText` est une recherche plein texte (« intern » ramène aussi « internal ») :
  le vrai filtrage se fait ensuite côté bot, par mots entiers.
- Mauvais `wd`/`site` -> HTTP 422 ou 404.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from internbot.errors import HttpError, ProviderError
from internbot.models import Job
from internbot.providers.base import (
    Provider,
    iso_date,
    join_locations,
    parse_items,
    register,
    require_key,
)

if TYPE_CHECKING:
    from internbot.config import CompanyConfig

log = logging.getLogger(__name__)

PAGE_SIZE = 20
_MULTI_LOC = re.compile(r"^\d+\s+locations?$", re.IGNORECASE)
_REQ_ID = re.compile(r"^[A-Za-z]{0,6}[-_]?\d[\w.-]{2,}$")
# Workday suffixe les publications multiples d'une même réquisition par « -1 », « -2 »…
# On ne retire que ces suffixes courts, pour ne pas tronquer un ID du type « 2024-0042 ».
_PATH_ID = re.compile(r"_([A-Za-z]{0,6}[-_]?\d[\w-]*?)(?:-\d{1,2})?$")
_DAYS_AGO = re.compile(r"posted\s+(\d+)\s+days?\s+ago", re.IGNORECASE)


@register
class WorkdayProvider(Provider):
    name = "workday"
    required_fields = ("tenant", "wd", "site")
    optional_fields = ("search_text", "max_pages", "applied_facets", "fetch_details", "max_details")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._details_done: dict[str, int] = {}

    @staticmethod
    def base_url(company: CompanyConfig) -> str:
        tenant, wd = company.opt("tenant"), company.opt("wd")
        return f"https://{tenant}.{wd}.myworkdayjobs.com"

    def fetch_jobs(self, company: CompanyConfig) -> list[Job]:
        tenant, site = company.opt("tenant"), company.opt("site")
        url = f"{self.base_url(company)}/wday/cxs/{tenant}/{site}/jobs"
        max_pages = int(company.opt("max_pages", 100))
        body: dict[str, Any] = {
            "appliedFacets": company.opt("applied_facets") or {},
            "limit": PAGE_SIZE,
            "offset": 0,
            "searchText": company.opt("search_text", "intern"),
        }

        postings: list[dict[str, Any]] = []
        total: int | None = None
        for page in range(max_pages):
            body["offset"] = page * PAGE_SIZE
            try:
                data = self.http.post_json(url, body)
            except HttpError as exc:
                hint = ""
                if exc.status in (400, 404, 422):
                    hint = " — vérifiez tenant/wd/site dans config.yaml (voir README)"
                raise ProviderError(f"[workday] {company.name} : {exc}{hint}") from None
            items = require_key(data, "jobPostings", provider="workday")
            if total is None:  # seul le total de la 1re page est fiable
                total = int(data.get("total") or 0)
            postings.extend(items)
            if not items or len(postings) >= total:
                break
        else:
            log.warning(
                "[workday] %s : limite de %d pages atteinte (%d/%s offres) — augmentez max_pages",
                company.name,
                max_pages,
                len(postings),
                total,
            )

        base = f"{self.base_url(company)}/{site}"
        return parse_items(postings, lambda p: self._parse(company, base, p), provider="workday")

    def _parse(self, company: CompanyConfig, base: str, p: dict[str, Any]) -> Job | None:
        title = p.get("title")
        path = p.get("externalPath")
        if not title or not path:
            return None
        location = str(p.get("locationsText") or "")
        return Job(
            company=company.name,
            job_id=extract_job_id(p),
            title=str(title).strip(),
            url=f"{base}{path}",
            source=self.name,
            location=location,
            location_complete=not _MULTI_LOC.match(location.strip()),
            posted_at=parse_posted_on(p.get("postedOn")),
            extra={"external_path": path},
        )

    def enrich(self, company: CompanyConfig, job: Job) -> Job:
        """Récupère le détail (tous les lieux + date de publication) d'une offre candidate."""
        if not company.opt("fetch_details", True):
            return job
        done = self._details_done.get(company.name, 0)
        if done >= int(company.opt("max_details", 25)):
            return job
        self._details_done[company.name] = done + 1
        tenant, site = company.opt("tenant"), company.opt("site")
        url = f"{self.base_url(company)}/wday/cxs/{tenant}/{site}{job.extra['external_path']}"
        try:
            data = self.http.get_json(url, headers={"Accept": "application/json"})
            info = data["jobPostingInfo"]
        except (HttpError, KeyError, TypeError) as exc:
            log.warning(
                "[workday] détail indisponible pour %s (%s) : %s", job.job_id, job.title, exc
            )
            return job
        location = join_locations(info.get("location"), info.get("additionalLocations") or [])
        return job.with_updates(
            location=location or job.location,
            location_complete=bool(location) or job.location_complete,
            posted_at=iso_date(info.get("startDate")) or job.posted_at,
            url=info.get("externalUrl") or job.url,
        )


def extract_job_id(p: dict[str, Any]) -> str:
    """ID stable : le numéro de réquisition (JR...) des bulletFields, sinon déduit du chemin."""
    for field in p.get("bulletFields") or []:
        if isinstance(field, str) and _REQ_ID.match(field.strip()):
            return field.strip()
    path = str(p.get("externalPath") or "")
    match = _PATH_ID.search(path)
    return match.group(1) if match else path


def parse_posted_on(value: Any, *, today: date | None = None) -> str | None:
    """« Posted Today » -> date ISO ; « Posted 30+ Days Ago » reste tel quel (approximatif)."""
    if not value:
        return None
    text = str(value).strip()
    today = today or datetime.now(UTC).date()
    lowered = text.lower()
    if lowered == "posted today":
        return today.isoformat()
    if lowered == "posted yesterday":
        return (today - timedelta(days=1)).isoformat()
    if "+" not in text and (m := _DAYS_AGO.match(text)):
        return (today - timedelta(days=int(m.group(1)))).isoformat()
    return text
