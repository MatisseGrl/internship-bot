"""Oracle Recruiting Cloud / Oracle HCM (Oracle, JPMorgan Chase…).

Endpoint REST appelé par le site carrières (« Candidate Experience ») lui-même :

    GET https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions
        ?onlyData=true&expand=requisitionList.secondaryLocations
        &finder=findReqs;siteNumber={site},keyword=intern,limit=25,offset=0,sortBy=POSTING_DATES_DESC

Réponse : {"items": [{"TotalJobsCount": N, "requisitionList": [{"Id", "Title",
"PrimaryLocation", "secondaryLocations": [{"Name"}], "PostedDate"}]}]}.
Lien public d'une offre : https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{Id}

La recherche par mot-clé est approximative (« intern » ramène aussi « internal ») : le
filtrage fin est fait par le bot, comme pour Workday.
"""

from __future__ import annotations

import logging
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

PAGE_SIZE = 25


@register
class OracleHcmProvider(Provider):
    name = "oracle_hcm"
    required_fields = ("host", "site")
    optional_fields = ("keyword", "max_pages", "lang")

    def fetch_jobs(self, company: CompanyConfig) -> list[Job]:
        host, site = company.opt("host"), company.opt("site")
        keyword = str(company.opt("keyword", "intern"))
        max_pages = int(company.opt("max_pages", 20))
        base = f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"

        reqs: list[Any] = []
        total = 0
        for page in range(max_pages):
            finder = (
                f"findReqs;siteNumber={site},keyword={keyword},limit={PAGE_SIZE},"
                f"offset={page * PAGE_SIZE},sortBy=POSTING_DATES_DESC"
            )
            # Le `finder` contient « ; » et « , » : on le met tel quel dans l'URL (comme le site).
            url = f"{base}?onlyData=true&expand=requisitionList.secondaryLocations&finder={finder}"
            try:
                data = self.http.get_json(url)
            except HttpError as exc:
                hint = " — vérifiez host/site (voir README)" if exc.status in (400, 404) else ""
                raise ProviderError(f"[oracle_hcm] {company.name} : {exc}{hint}") from None
            search = require_key(data, "items", provider=self.name)
            if not search or not isinstance(search[0], dict):
                break
            batch = require_key(search[0], "requisitionList", provider=self.name)
            if page == 0:
                total = int(search[0].get("TotalJobsCount") or 0)
            reqs.extend(batch)
            if not batch or len(reqs) >= total:
                break
        else:
            log.warning(
                "[oracle_hcm] %s : limite de %d pages atteinte (%d/%d offres)",
                company.name,
                max_pages,
                len(reqs),
                total,
            )
        lang = company.opt("lang", "en")
        public = f"https://{host}/hcmUI/CandidateExperience/{lang}/sites/{site}/job"
        return parse_items(reqs, lambda r: self._parse(company, public, r), provider=self.name)

    def _parse(self, company: CompanyConfig, public: str, r: dict[str, Any]) -> Job | None:
        if not r.get("Id") or not r.get("Title"):
            return None
        secondary = [
            loc.get("Name") for loc in r.get("secondaryLocations") or [] if isinstance(loc, dict)
        ]
        return Job(
            company=company.name,
            job_id=str(r["Id"]),
            title=" ".join(str(r["Title"]).split()),
            url=f"{public}/{r['Id']}",
            source=self.name,
            location=join_locations(r.get("PrimaryLocation"), secondary),
            posted_at=iso_date(r.get("PostedDate")),
        )
