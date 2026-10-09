"""Sitemap XML d'un site carrières (Intuit, Arm… : sites Radancy / TalentBrew).

Sur ces sites, la page de recherche (`/search-jobs/`) est interdite aux robots par robots.txt,
mais le sitemap — publié précisément pour les robots — liste toutes les offres ouvertes :

    https://jobs.intuit.com/job/mountain-view/summer-2027-software-engineering-intern/27595/99856180864

Le titre et le lieu sont reconstruits à partir de l'URL (« summer-2027-software-engineering-intern »
-> « Summer 2027 Software Engineering Intern ») : approximatif (pas de « C++ », ni de virgules),
mais suffisant pour les filtres par mots entiers. Une requête par run (plus une par sous-sitemap
si le site publie un index de sitemaps).

    - name: Intuit
      provider: sitemap
      url: https://jobs.intuit.com/sitemap.xml
      job_pattern: "/job/(?P<location>[^/]+)/(?P<slug>[^/]+)/\\d+/(?P<id>\\d+)$"   # défaut

Sites Phenom (RTX, Thales…) : `job_pattern: "/job/(?P<id>[^/]+)/(?P<slug>[^/?#]+)$"` (pas de
lieu dans l'URL). Un index de sitemaps est suivi (au plus `max_sitemaps`, défaut 20).
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote

from internbot.errors import HttpError, ProviderError, ProviderFormatError
from internbot.models import Job
from internbot.providers.base import Provider, parse_items, register

if TYPE_CHECKING:
    from internbot.config import CompanyConfig

log = logging.getLogger(__name__)

# Format TalentBrew : /job/{ville}/{slug-du-titre}/{id-organisation}/{id-offre}
DEFAULT_PATTERN = r"/job/(?P<location>[^/]+)/(?P<slug>[^/]+)/\d+/(?P<id>\d+)/?$"
_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
MAX_CHILD_SITEMAPS = 20


def slug_to_text(slug: str) -> str:
    """« summer-2027-software-intern » -> « Summer 2027 Software Intern »."""
    words = unquote(slug).replace("_", "-").split("-")
    return " ".join(w if any(c.isdigit() for c in w) else w.capitalize() for w in words if w)


@register
class SitemapProvider(Provider):
    name = "sitemap"
    required_fields = ("url",)
    optional_fields = ("job_pattern", "max_sitemaps")

    def fetch_jobs(self, company: CompanyConfig) -> list[Job]:
        pattern = re.compile(str(company.opt("job_pattern") or DEFAULT_PATTERN))
        if "id" not in pattern.groupindex or "slug" not in pattern.groupindex:
            raise ProviderError(
                f"[sitemap] {company.name} : job_pattern doit nommer (?P<id>…) et (?P<slug>…)"
            )
        locs = self._locs(company, str(company.opt("url")))
        children = [u for u in locs if u.endswith(".xml")]
        if children and not any(pattern.search(u) for u in locs):  # index de sitemaps
            locs = []
            for child in children[: int(company.opt("max_sitemaps", MAX_CHILD_SITEMAPS))]:
                locs.extend(self._locs(company, child))
        rows = [{"url": u, **m.groupdict()} for u in locs if (m := pattern.search(u))]
        if locs and not rows:
            raise ProviderFormatError(
                f"[sitemap] {company.name} : aucune des {len(locs)} URL ne ressemble à une offre "
                "(job_pattern) : format modifié ?"
            )
        return parse_items(rows, lambda r: self._parse(company, r), provider=self.name)

    def _locs(self, company: CompanyConfig, url: str) -> list[str]:
        try:
            resp = self.http.request("GET", url)
        except HttpError as exc:
            raise ProviderError(f"[sitemap] {company.name} : {exc}") from None
        if "<urlset" not in resp.text and "<sitemapindex" not in resp.text:
            raise ProviderFormatError(f"[sitemap] {company.name} : {url} n'est pas un sitemap XML")
        return [loc.replace("&amp;", "&") for loc in _LOC.findall(resp.text)]

    def _parse(self, company: CompanyConfig, row: dict[str, Any]) -> Job | None:
        if not row.get("id") or not row.get("slug"):
            return None
        return Job(
            company=company.name,
            job_id=str(row["id"]),
            title=slug_to_text(str(row["slug"])),
            url=str(row["url"]),
            source=self.name,
            location=slug_to_text(str(row.get("location") or "")),
        )
