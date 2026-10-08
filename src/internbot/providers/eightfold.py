"""Eightfold (Netflix, Qualcomm…) : endpoint JSON appelé par le site carrières lui-même.

Deux versions coexistent selon les entreprises (constaté le 9 oct. 2026) :

- `v2`   : GET https://{host}/api/apply/v2/jobs?domain={domain}&query=intern&start=0&num=10
           -> {"positions": [...], "count": N}     (Netflix : explore.jobs.netflix.net)
- `pcsx` : GET https://{host}/api/pcsx/search?domain={domain}&query=intern&location=&start=0
           -> {"data": {"positions": [...], "count": N}}  (Qualcomm : careers.qualcomm.com)

Un site en `pcsx` répond 403 « Not authorized for PCSX »… sur l'API v2, et inversement : le
champ `api` dit laquelle utiliser. 10 offres par page dans les deux cas.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from internbot.errors import HttpError, ProviderError, ProviderFormatError
from internbot.models import Job
from internbot.providers.base import (
    Provider,
    epoch_date,
    get_path,
    join_locations,
    parse_items,
    register,
)

if TYPE_CHECKING:
    from internbot.config import CompanyConfig

log = logging.getLogger(__name__)

PAGE_SIZE = 10


@register
class EightfoldProvider(Provider):
    name = "eightfold"
    required_fields = ("host", "domain")
    optional_fields = ("api", "query", "max_pages")

    def fetch_jobs(self, company: CompanyConfig) -> list[Job]:
        host, domain = company.opt("host"), company.opt("domain")
        api = str(company.opt("api", "v2"))
        if api not in ("v2", "pcsx"):
            raise ProviderError(f"[eightfold] {company.name} : api doit valoir v2 ou pcsx")
        query = company.opt("query", "intern")
        max_pages = int(company.opt("max_pages", 30))
        if api == "v2":
            url = f"https://{host}/api/apply/v2/jobs"
            items_path, total_path = "positions", "count"
        else:
            url = f"https://{host}/api/pcsx/search"
            items_path, total_path = "data.positions", "data.count"

        items: list[Any] = []
        total = 0
        for page in range(max_pages):
            params: dict[str, Any] = {"domain": domain, "query": query, "start": page * PAGE_SIZE}
            if api == "v2":
                params["num"] = PAGE_SIZE
            else:
                params["location"] = ""
            try:
                data = self.http.get_json(url, params=params)
            except HttpError as exc:
                hint = " — essayez l'autre valeur de `api` (v2 / pcsx)" if exc.status == 403 else ""
                raise ProviderError(f"[eightfold] {company.name} : {exc}{hint}") from None
            batch = get_path(data, items_path)
            if not isinstance(batch, list):
                raise ProviderFormatError(
                    f"[eightfold] {company.name} : '{items_path}' absent : format modifié ?"
                )
            if page == 0:
                total = int(get_path(data, total_path) or 0)
            items.extend(batch)
            if not batch or len(items) >= total:
                break
        else:
            log.warning(
                "[eightfold] %s : limite de %d pages atteinte (%d/%d offres)",
                company.name,
                max_pages,
                len(items),
                total,
            )
        return parse_items(items, lambda p: self._parse(company, str(host), p), provider=self.name)

    def _parse(self, company: CompanyConfig, host: str, p: dict[str, Any]) -> Job | None:
        # v2 : snake_case ; pcsx : camelCase.
        title = p.get("name") or p.get("posting_name")
        job_id = (
            p.get("display_job_id") or p.get("displayJobId") or p.get("ats_job_id") or p.get("id")
        )
        url = p.get("canonicalPositionUrl") or (
            f"https://{host}{p['positionUrl']}" if p.get("positionUrl") else None
        )
        if not url and p.get("id"):
            url = f"https://{host}/careers/job/{p['id']}"
        if not title or not job_id or not url:
            return None
        locations = p.get("locations") or p.get("location") or []
        return Job(
            company=company.name,
            job_id=str(job_id),
            title=" ".join(str(title).split()),
            url=str(url),
            source=self.name,
            location=join_locations(locations),
            posted_at=epoch_date(p.get("t_create") or p.get("postedTs") or p.get("creationTs")),
        )
