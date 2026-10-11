"""Offres Dassault Systèmes, servies par le moteur Exalead du site 3ds.com.

La page https://www.3ds.com/careers/jobs appelle ``/apisearch/card_search_api`` : chaque résultat
est une « carte » dont les champs sont une liste ``metas`` de ``{name, value}`` (un même nom peut
revenir plusieurs fois, d'où ce provider dédié). ``hf`` fixe le nombre de résultats par page,
``b`` l'index du premier.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from internbot.errors import HttpError, ProviderError, ProviderFormatError
from internbot.models import Job
from internbot.providers.base import Provider, register

if TYPE_CHECKING:
    from internbot.config import CompanyConfig

log = logging.getLogger(__name__)

_QUERY = '#all card_content_lang:en (card_content_type="career")'


def card_values(hit: dict[str, Any]) -> dict[str, list[str]]:
    """Regroupe les ``metas`` d'une carte par nom (un nom peut apparaître plusieurs fois)."""
    values: dict[str, list[str]] = {}
    for meta in hit.get("metas") or []:
        name, value = meta.get("name"), meta.get("value")
        if name and value not in (None, ""):
            values.setdefault(str(name), []).append(str(value))
    return values


def _date(text: str | None) -> str | None:
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y/%m/%d").date().isoformat()
    except ValueError:
        return None


@register
class ExaleadProvider(Provider):
    name = "exalead"
    required_fields = ("api_url",)
    optional_fields = ("page_size", "max_pages", "query")

    def fetch_jobs(self, company: CompanyConfig) -> list[Job]:
        api_url = str(company.opt("api_url"))
        page_size = int(company.opt("page_size", 200))
        max_pages = int(company.opt("max_pages", 10))
        query = str(company.opt("query", _QUERY))
        if page_size < 1 or max_pages < 1:
            raise ProviderError(f"[exalead] {company.name} : page_size et max_pages positifs")
        jobs: list[Job] = []
        seen: set[str] = set()
        total: int | None = None
        for page in range(max_pages):
            try:
                data = self.http.get_json(
                    api_url,
                    params={
                        "q": query,
                        "s": "desc(card_content_start_datetime)",
                        "b": page * page_size,
                        "hf": page_size,
                        "output_format": "json",
                    },
                )
            except HttpError as exc:
                raise ProviderError(f"[exalead] {company.name} : {exc}") from None
            hits = data.get("hits") if isinstance(data, dict) else None
            if not isinstance(hits, list) or not isinstance(data.get("nhits"), int):
                raise ProviderFormatError(
                    f"[exalead] {company.name} : 'hits'/'nhits' absents, format modifié ?"
                )
            total = data["nhits"]
            if page == 0 and total and not hits:
                raise ProviderFormatError(f"[exalead] {company.name} : aucune carte lisible")
            for hit in hits:
                job = self._parse(company, hit)
                if job and job.job_id not in seen:
                    seen.add(job.job_id)
                    jobs.append(job)
            if not hits or (page + 1) * page_size >= total:
                break
        else:
            log.warning(
                "[exalead] %s : limite de %d pages atteinte (%d/%s offres)",
                company.name,
                max_pages,
                len(jobs),
                total,
            )
        return jobs

    def _parse(self, company: CompanyConfig, hit: dict[str, Any]) -> Job | None:
        values = card_values(hit)

        def first(name: str) -> str:
            return values.get(name, [""])[0]

        job_id, title = first("card_id"), " ".join(first("content_title").split())
        url = first("content_cta_1_url") or first("content_cta_1_url_id")
        if not job_id or not title or not url:
            return None
        return Job(
            company=company.name,
            job_id=job_id,
            title=title,
            url=url,
            source=self.name,
            location=first("content_info_2_value"),
            posted_at=_date(first("content_start_datetime")),
        )
