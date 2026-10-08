"""Apple (site maison jobs.apple.com), page de recherche publique, paginée (20 offres par page).

GET https://jobs.apple.com/en-us/search?team=internships-STDNT-INTRN&page=1

Pas d'API publique documentée : les résultats sont embarqués dans le HTML de la page, dans
`window.__staticRouterHydrationData = JSON.parse("...")` (données de rendu côté serveur),
sous `loaderData.search` : `searchResults` (offres) et `totalRecords`.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from internbot.errors import HttpError, ProviderError, ProviderFormatError
from internbot.models import Job
from internbot.providers.base import Provider, iso_date, parse_items, register, require_key

if TYPE_CHECKING:
    from internbot.config import CompanyConfig

log = logging.getLogger(__name__)

BASE = "https://jobs.apple.com/en-us"
DEFAULT_TEAM = "internships-STDNT-INTRN"  # filtre « Students: Internships » du site
HYDRATION_RE = re.compile(
    r"window\.__staticRouterHydrationData\s*=\s*JSON\.parse\((\".*?\")\);", re.S
)


def extract_search(html: str) -> dict[str, Any]:
    """Extrait `loaderData.search` des données de rendu embarquées dans la page."""
    match = HYDRATION_RE.search(html)
    if not match:
        raise ProviderFormatError("[apple] données de la page introuvables : format modifié ?")
    try:
        # Double décodage : littéral de chaîne JS, puis le JSON qu'il contient.
        data = json.loads(json.loads(match.group(1)))
        search = data["loaderData"]["search"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ProviderFormatError(f"[apple] données de la page illisibles ({exc})") from None
    if not isinstance(search, dict):
        raise ProviderFormatError("[apple] 'loaderData.search' n'est pas un objet")
    return search


@register
class AppleProvider(Provider):
    name = "apple"
    optional_fields = ("team", "max_pages")

    def fetch_jobs(self, company: CompanyConfig) -> list[Job]:
        team = company.opt("team", DEFAULT_TEAM)
        max_pages = int(company.opt("max_pages", 20))
        items: list[Any] = []
        total = 0
        for page in range(1, max_pages + 1):
            try:
                resp = self.http.request(
                    "GET", f"{BASE}/search", params={"team": team, "page": page}
                )
            except HttpError as exc:
                raise ProviderError(f"[apple] {company.name} : {exc}") from None
            search = extract_search(resp.text)
            results = require_key(search, "searchResults", provider=self.name)
            total = int(search.get("totalRecords") or 0)
            items.extend(results)
            if not results or len(items) >= total:
                break
        else:
            log.warning("[apple] %s : limite de pages atteinte (%s offres)", company.name, total)
        return parse_items(items, lambda r: self._parse(company, r), provider=self.name)

    def _parse(self, company: CompanyConfig, r: dict[str, Any]) -> Job | None:
        # `id` (ex: 200687446-1731) est propre à chaque publication : une même offre publiée
        # dans plusieurs pays a le même `positionId` mais des `id` différents.
        job_id = r.get("id") or r.get("reqId")
        title = str(r.get("postingTitle") or "").strip()
        if not job_id or not title:
            return None
        slug = r.get("transformedPostingTitle") or "-"
        return Job(
            company=company.name,
            job_id=str(job_id),
            title=title,
            url=f"{BASE}/details/{job_id}/{slug}",
            source=self.name,
            location=_location(r.get("locations")),
            posted_at=iso_date(r.get("postDateInGMT")),
        )


def _location(locations: Any) -> str:
    """« Munich, Germany » ; « United States » quand le lieu est le pays lui-même."""
    parts: list[str] = []
    for loc in locations if isinstance(locations, list) else []:
        if not isinstance(loc, dict):
            continue
        name = str(loc.get("name") or "").strip()
        country = str(loc.get("countryName") or "").strip()
        if not name or not country or country.startswith(name):
            text = name or country  # lieu = pays (« United States » / « ... of America »)
        else:
            text = f"{name}, {country}"
        if text and text not in parts:
            parts.append(text)
    return " · ".join(parts)
