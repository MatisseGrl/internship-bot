"""Ashby Job Posting API (publique, officielle).

GET https://api.ashbyhq.com/posting-api/job-board/{board}
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

API = "https://api.ashbyhq.com/posting-api/job-board/{board}"


@register
class AshbyProvider(Provider):
    name = "ashby"
    required_fields = ("board",)

    def fetch_jobs(self, company: CompanyConfig) -> list[Job]:
        try:
            data = self.http.get_json(API.format(board=company.opt("board")))
        except HttpError as exc:
            raise ProviderError(f"[ashby] {company.name} : {exc}") from None
        items = require_key(data, "jobs", provider=self.name)
        listed = [j for j in items if not isinstance(j, dict) or j.get("isListed", True)]
        return parse_items(listed, lambda j: self._parse(company, j), provider=self.name)

    def _parse(self, company: CompanyConfig, j: dict[str, Any]) -> Job | None:
        url = j.get("jobUrl")
        if not j.get("title") or not url:
            return None
        secondary = [
            s.get("location") if isinstance(s, dict) else s
            for s in (j.get("secondaryLocations") or [])
        ]
        location = join_locations(j.get("location"), secondary)
        if j.get("isRemote") and "remote" not in location.lower():
            location = join_locations(location, "Remote")
        return Job(
            company=company.name,
            job_id=str(j.get("id") or url),
            title=str(j["title"]).strip(),
            url=str(url),
            source=self.name,
            location=location,
            posted_at=iso_date(j.get("publishedAt")),
        )
