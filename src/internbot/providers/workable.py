"""Workable (widget public, utilisé par les pages carrières embarquées).

GET https://apply.workable.com/api/v1/widget/accounts/{account}
(vérifié : renvoie {"name", "description", "jobs": [...]} avec shortcode, url, city, country...)
"""

from __future__ import annotations

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

API = "https://apply.workable.com/api/v1/widget/accounts/{account}"


@register
class WorkableProvider(Provider):
    name = "workable"
    required_fields = ("account",)

    def fetch_jobs(self, company: CompanyConfig) -> list[Job]:
        try:
            data = self.http.get_json(API.format(account=company.opt("account")))
        except HttpError as exc:
            raise ProviderError(f"[workable] {company.name} : {exc}") from None
        items = require_key(data, "jobs", provider=self.name)
        return parse_items(items, lambda j: self._parse(company, j), provider=self.name)

    def _parse(self, company: CompanyConfig, j: dict[str, Any]) -> Job | None:
        code = j.get("shortcode")
        if not code or not j.get("title"):
            return None
        locations = [
            ", ".join(str(x) for x in (loc.get("city"), loc.get("country")) if x)
            for loc in (j.get("locations") or [])
            if isinstance(loc, dict) and not loc.get("hidden")
        ]
        if not locations:
            locations = [", ".join(str(x) for x in (j.get("city"), j.get("country")) if x)]
        location = join_locations(locations)
        if j.get("telecommuting") and "remote" not in location.lower():
            location = join_locations(location, "Remote")
        return Job(
            company=company.name,
            job_id=str(code),
            title=str(j["title"]).strip(),
            url=str(j.get("url") or f"https://apply.workable.com/j/{code}"),
            source=self.name,
            location=location,
            posted_at=iso_date(j.get("published_on") or j.get("created_at")),
        )
