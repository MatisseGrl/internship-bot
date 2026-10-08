"""SmartRecruiters Posting API (publique, officielle), paginée.

GET https://api.smartrecruiters.com/v1/companies/{company_id}/postings?q=intern&limit=100&offset=0
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from internbot.errors import HttpError, ProviderError
from internbot.models import Job
from internbot.providers.base import Provider, iso_date, parse_items, register, require_key

if TYPE_CHECKING:
    from internbot.config import CompanyConfig

log = logging.getLogger(__name__)

API = "https://api.smartrecruiters.com/v1/companies/{company_id}/postings"
PAGE_SIZE = 100


@register
class SmartRecruitersProvider(Provider):
    name = "smartrecruiters"
    required_fields = ("company_id",)
    optional_fields = ("query", "max_pages")

    def fetch_jobs(self, company: CompanyConfig) -> list[Job]:
        company_id = company.opt("company_id")
        url = API.format(company_id=company_id)
        max_pages = int(company.opt("max_pages", 20))
        items: list[Any] = []
        total = None
        for page in range(max_pages):
            params: dict[str, Any] = {"limit": PAGE_SIZE, "offset": page * PAGE_SIZE}
            query = company.opt("query", "intern")
            if query:
                params["q"] = query
            try:
                data = self.http.get_json(url, params=params)
            except HttpError as exc:
                raise ProviderError(f"[smartrecruiters] {company.name} : {exc}") from None
            content = require_key(data, "content", provider=self.name)
            total = int(data.get("totalFound") or 0)
            items.extend(content)
            if not content or len(items) >= total:
                break
        else:
            log.warning(
                "[smartrecruiters] %s : limite de pages atteinte (%s offres)", company.name, total
            )
        return parse_items(
            items, lambda p: self._parse(company, str(company_id), p), provider=self.name
        )

    def _parse(self, company: CompanyConfig, company_id: str, p: dict[str, Any]) -> Job | None:
        if not p.get("id") or not p.get("name"):
            return None
        loc = p.get("location") or {}
        location = loc.get("fullLocation") or ", ".join(
            str(x) for x in (loc.get("city"), loc.get("region"), loc.get("country")) if x
        )
        if loc.get("remote") and "remote" not in location.lower():
            location = f"{location} · Remote" if location else "Remote"
        return Job(
            company=company.name,
            job_id=str(p["id"]),
            title=str(p["name"]).strip(),
            url=f"https://jobs.smartrecruiters.com/{company_id}/{p['id']}",
            source=self.name,
            location=str(location),
            posted_at=iso_date(p.get("releasedDate")),
        )
