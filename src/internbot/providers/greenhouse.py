"""Greenhouse Job Board API (publique, officielle).

GET https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=false
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from internbot.errors import HttpError, ProviderError
from internbot.models import Job
from internbot.providers.base import Provider, iso_date, parse_items, register, require_key

if TYPE_CHECKING:
    from internbot.config import CompanyConfig

API = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"


@register
class GreenhouseProvider(Provider):
    name = "greenhouse"
    required_fields = ("board",)

    def fetch_jobs(self, company: CompanyConfig) -> list[Job]:
        try:
            data = self.http.get_json(
                API.format(board=company.opt("board")), params={"content": "false"}
            )
        except HttpError as exc:
            hint = (
                " — board inconnu ? (voir l'URL boards.greenhouse.io/<board>)"
                if (exc.status == 404)
                else ""
            )
            raise ProviderError(f"[greenhouse] {company.name} : {exc}{hint}") from None
        items = require_key(data, "jobs", provider=self.name)
        return parse_items(items, lambda j: self._parse(company, j), provider=self.name)

    def _parse(self, company: CompanyConfig, j: dict[str, Any]) -> Job | None:
        if not j.get("id") or not j.get("title") or not j.get("absolute_url"):
            return None
        location = (j.get("location") or {}).get("name", "")
        return Job(
            company=company.name,
            job_id=str(j["id"]),
            title=str(j["title"]).strip(),
            url=str(j["absolute_url"]),
            source=self.name,
            location=str(location or ""),
            posted_at=iso_date(j.get("first_published") or j.get("updated_at")),
        )
