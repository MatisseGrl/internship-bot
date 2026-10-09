"""Flux RSS publics d'offres, notamment ceux publiés par Teamtailor.

Le flux ``/jobs.rss`` de Teamtailor contient toutes les offres, un GUID stable et les
lieux dans l'espace de noms ``https://teamtailor.com/locations``. Une seule requête
est nécessaire par passage et aucune page de candidature n'est interrogée.
"""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING
from xml.etree import ElementTree as ET

from internbot.errors import HttpError, ProviderError, ProviderFormatError
from internbot.models import Job
from internbot.providers.base import Provider, join_locations, register

if TYPE_CHECKING:
    from internbot.config import CompanyConfig

TEAMTAILOR = "https://teamtailor.com/locations"


@register
class RssProvider(Provider):
    name = "rss"
    required_fields = ("url",)

    def fetch_jobs(self, company: CompanyConfig) -> list[Job]:
        url = str(company.opt("url"))
        try:
            response = self.http.request("GET", url)
        except HttpError as exc:
            raise ProviderError(f"[rss] {company.name} : {exc}") from None
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            raise ProviderFormatError(f"[rss] {company.name} : XML invalide : {exc}") from None
        if root.tag != "rss" or root.find("channel") is None:
            raise ProviderFormatError(f"[rss] {company.name} : canal RSS absent")

        jobs: list[Job] = []
        items = root.findall("channel/item")
        for item in items:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            guid = (item.findtext("guid") or link).strip()
            if not title or not link or not guid:
                continue
            locations = [
                location.findtext(f"{{{TEAMTAILOR}}}name")
                or location.findtext(f"{{{TEAMTAILOR}}}city")
                for location in item.findall(f"{{{TEAMTAILOR}}}locations/{{{TEAMTAILOR}}}location")
            ]
            date = None
            if raw_date := item.findtext("pubDate"):
                with suppress(TypeError, ValueError, OverflowError):
                    date = parsedate_to_datetime(raw_date).astimezone(UTC).date().isoformat()
            jobs.append(
                Job(
                    company=company.name,
                    job_id=guid,
                    title=" ".join(title.split()),
                    url=link,
                    source=self.name,
                    location=join_locations(*locations),
                    posted_at=date,
                )
            )
        if items and not jobs:
            raise ProviderFormatError(
                f"[rss] {company.name} : aucune des {len(items)} offres n'a pu être lue"
            )
        return jobs
