"""Avature (Electronic Arts, IBM…) : page de résultats publique, rendue côté serveur.

    GET {base_url}/SearchJobs/?search=intern&jobRecordsPerPage=20&jobOffset=0

Avature n'a pas d'API publique et son flux RSS ignore la recherche et la pagination (il renvoie
toujours les 20 mêmes offres, constaté chez EA le 9 oct. 2026). La page HTML, elle, est rendue
côté serveur (aucun JavaScript nécessaire) : chaque offre est un
`<article class="article--result">` contenant le lien
`<a class="... link_result" href=".../JobDetail/{slug}/{id}">` et le lieu
`<span class="list-item-location">`. Le total vient du texte « 21 - 40 of 135 ».
"""

from __future__ import annotations

import html
import logging
import re
from typing import TYPE_CHECKING, Any

from internbot.errors import HttpError, ProviderError, ProviderFormatError
from internbot.models import Job
from internbot.providers.base import Provider, parse_items, register

if TYPE_CHECKING:
    from internbot.config import CompanyConfig

log = logging.getLogger(__name__)

PAGE_SIZE = 20
_ARTICLE = re.compile(r"<article\b[^>]*\barticle--result\b.*?</article>", re.S)
_LINK = re.compile(r'<a\b[^>]*\blink_result\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_LOCATION = re.compile(r'<span class="list-item-location">(.*?)</span>', re.S)
_TOTAL = re.compile(r"\b\d+\s*-\s*\d+\s+of\s+(\d+)\b")
_ID = re.compile(r"/(\d+)/?(?:[?#].*)?$")
_TAGS = re.compile(r"<[^>]+>")


def _text(fragment: str) -> str:
    return " ".join(html.unescape(_TAGS.sub(" ", fragment)).split())


def parse_results(page: str) -> tuple[list[dict[str, Any]], int | None]:
    """Offres d'une page de résultats Avature, et nombre total annoncé (None si absent)."""
    rows = []
    for article in _ARTICLE.findall(page):
        link = _LINK.search(article)
        if not link:
            continue
        location = _LOCATION.search(article)
        rows.append(
            {
                "href": html.unescape(link.group(1)),
                "title": _text(link.group(2)),
                "location": _text(location.group(1)) if location else "",
            }
        )
    total = _TOTAL.search(page)
    return rows, int(total.group(1)) if total else None


@register
class AvatureProvider(Provider):
    name = "avature"
    required_fields = ("base_url",)
    optional_fields = ("query", "max_pages", "page_size")

    def fetch_jobs(self, company: CompanyConfig) -> list[Job]:
        base = str(company.opt("base_url")).rstrip("/")
        query = company.opt("query", "intern")
        max_pages = int(company.opt("max_pages", 15))
        page_size = int(company.opt("page_size", PAGE_SIZE))
        rows: list[dict[str, Any]] = []
        total: int | None = None
        for page in range(max_pages):
            params: dict[str, Any] = {"jobRecordsPerPage": page_size, "jobOffset": page * page_size}
            if query:
                params["search"] = query
            try:
                resp = self.http.request("GET", f"{base}/SearchJobs/", params=params)
            except HttpError as exc:
                raise ProviderError(f"[avature] {company.name} : {exc}") from None
            batch, page_total = parse_results(resp.text)
            if page == 0:
                if not batch and page_total is None:
                    raise ProviderFormatError(
                        f"[avature] {company.name} : aucune offre ni total dans la page : "
                        "format modifié ?"
                    )
                total = page_total
            rows.extend(batch)
            if len(batch) < page_size or (total is not None and len(rows) >= total):
                break
        else:
            log.warning(
                "[avature] %s : limite de %d pages atteinte (%d/%s offres)",
                company.name,
                max_pages,
                len(rows),
                total,
            )
        return parse_items(rows, lambda r: self._parse(company, r), provider=self.name)

    def _parse(self, company: CompanyConfig, row: dict[str, Any]) -> Job | None:
        href, title = row.get("href"), row.get("title")
        match = _ID.search(str(href or ""))
        if not href or not title or not match:
            return None
        return Job(
            company=company.name,
            job_id=match.group(1),
            title=str(title),
            url=str(href),
            source=self.name,
            location=str(row.get("location") or ""),
        )
