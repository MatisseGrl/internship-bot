"""Lever Postings API (publique, officielle).

GET https://api.lever.co/v0/postings/{company}?mode=json
(instances européennes : https://api.eu.lever.co, option `region: eu`)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from internbot.errors import HttpError, ProviderError, ProviderFormatError
from internbot.models import Job
from internbot.providers.base import Provider, iso_date, join_locations, parse_items, register

if TYPE_CHECKING:
    from internbot.config import CompanyConfig

HOSTS = {"global": "https://api.lever.co", "eu": "https://api.eu.lever.co"}


@register
class LeverProvider(Provider):
    name = "lever"
    required_fields = ("company",)
    optional_fields = ("region",)

    def fetch_jobs(self, company: CompanyConfig) -> list[Job]:
        region = str(company.opt("region", "global")).lower()
        host = HOSTS.get(region)
        if host is None:
            raise ProviderError(f"[lever] {company.name} : region '{region}' inconnue (global|eu)")
        url = f"{host}/v0/postings/{company.opt('company')}"
        try:
            data = self.http.get_json(url, params={"mode": "json"})
        except HttpError as exc:
            hint = " — slug inconnu, ou instance EU (region: eu) ?" if exc.status == 404 else ""
            raise ProviderError(f"[lever] {company.name} : {exc}{hint}") from None
        if not isinstance(data, list):
            raise ProviderFormatError(
                f"[lever] réponse inattendue (liste attendue, reçu {type(data).__name__})"
            )
        return parse_items(data, lambda p: self._parse(company, p), provider=self.name)

    def _parse(self, company: CompanyConfig, p: dict[str, Any]) -> Job | None:
        if not p.get("id") or not p.get("text") or not p.get("hostedUrl"):
            return None
        cats = p.get("categories") or {}
        location = join_locations(cats.get("location"), cats.get("allLocations") or [])
        if p.get("workplaceType") == "remote" and "remote" not in location.lower():
            location = join_locations(location, "Remote")
        return Job(
            company=company.name,
            job_id=str(p["id"]),
            title=str(p["text"]).strip(),
            url=str(p["hostedUrl"]),
            source=self.name,
            location=location,
            posted_at=iso_date(p.get("createdAt")),
        )
