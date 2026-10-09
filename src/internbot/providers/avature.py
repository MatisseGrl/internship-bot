"""Avature (Electronic Arts, Siemens, TotalEnergies…) : résultats publics côté serveur.

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
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

from internbot.errors import HttpError, ProviderError, ProviderFormatError
from internbot.models import Job
from internbot.providers.base import Provider, parse_items, register

if TYPE_CHECKING:
    from internbot.config import CompanyConfig

log = logging.getLogger(__name__)

PAGE_SIZE = 20
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "wbr"}
_RESULT = re.compile(r'<(?:article|div)\b[^>]*\bclass="[^"]*\barticle--result\b[^"]*"[^>]*>', re.I)
_LINK = re.compile(r'<a\b[^>]*\bhref="([^"]*/JobDetail/[^"]+)"[^>]*>(.*?)</a>', re.S | re.I)
_TOTAL = re.compile(r"\b\d+\s*-\s*\d+\s+of\s+(\d+)(\+?)", re.I)
_ZERO = re.compile(
    r'<div\b[^>]*\bclass="[^"]*\blist-controls__text__legend\b[^"]*"[^>]*'
    r'\baria-label="0 results"',
    re.I,
)
_ID = re.compile(r"/(\d+)/?(?:[?#].*)?$")
_TAGS = re.compile(r"<[^>]+>")


def _text(fragment: str) -> str:
    return " ".join(html.unescape(_TAGS.sub(" ", fragment)).split())


class _ClassText(HTMLParser):
    """Récupère le texte d'un élément CSS, y compris ses sous-éléments imbriqués."""

    def __init__(self, class_name: str) -> None:
        super().__init__()
        self.class_name = class_name
        self.depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.depth and tag not in _VOID_TAGS:
            self.depth += 1
        elif self.class_name in (dict(attrs).get("class") or "").split():
            self.depth = 1

    def handle_endtag(self, tag: str) -> None:
        if self.depth:
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.depth:
            self.parts.append(data)


def _class_text(fragment: str, class_name: str) -> str:
    parser = _ClassText(class_name)
    parser.feed(fragment)
    return " ".join(" ".join(parser.parts).split()).replace(" ,", ",")


def parse_results(page: str) -> tuple[list[dict[str, Any]], int | None]:
    """Offres d'une page de résultats Avature, et nombre total annoncé (None si absent)."""
    rows = []
    starts = [match.start() for match in _RESULT.finditer(page)]
    for index, start in enumerate(starts):
        result = page[start : starts[index + 1] if index + 1 < len(starts) else len(page)]
        link = _LINK.search(result)
        if not link:
            continue
        location = _class_text(result, "list-item-location") or _class_text(
            result, "list-item-jobCountry"
        )
        rows.append(
            {
                "href": html.unescape(link.group(1)),
                "title": _text(link.group(2)),
                "location": location,
            }
        )
    total = _TOTAL.search(page)
    if total and not total.group(2):
        return rows, int(total.group(1))
    return rows, 0 if _ZERO.search(page) else None


@register
class AvatureProvider(Provider):
    name = "avature"
    required_fields = ("base_url",)
    optional_fields = (
        "query",
        "queries",
        "max_pages",
        "page_size",
        "offset_param",
        "page_size_param",
    )

    def fetch_jobs(self, company: CompanyConfig) -> list[Job]:
        base = str(company.opt("base_url")).rstrip("/")
        queries = company.opt("queries")
        if queries is None:
            queries = [company.opt("query", "intern")]
        if (
            not isinstance(queries, list)
            or not queries
            or not all(isinstance(q, str) and q.strip() for q in queries)
        ):
            raise ProviderError(
                f"[avature] {company.name} : queries doit être une liste de textes non vides"
            )
        max_pages = int(company.opt("max_pages", 15))
        page_size = int(company.opt("page_size", PAGE_SIZE))
        offset_param = str(company.opt("offset_param", "jobOffset"))
        page_size_param = str(company.opt("page_size_param", "jobRecordsPerPage"))
        jobs: list[Job] = []
        seen: set[str] = set()
        for query in queries:
            for job in self._fetch_query(
                company, base, query, max_pages, page_size, offset_param, page_size_param
            ):
                if job.job_id not in seen:
                    seen.add(job.job_id)
                    jobs.append(job)
        return jobs

    def _fetch_query(
        self,
        company: CompanyConfig,
        base: str,
        query: str,
        max_pages: int,
        page_size: int,
        offset_param: str,
        page_size_param: str,
    ) -> list[Job]:
        rows: list[dict[str, Any]] = []
        seen_hrefs: set[str] = set()
        total: int | None = None
        offset = 0
        for page in range(max_pages):
            params: dict[str, Any] = {page_size_param: page_size, offset_param: offset}
            if query:
                params["search"] = query
            try:
                resp = self.http.request("GET", f"{base}/SearchJobs/", params=params)
            except HttpError as exc:
                raise ProviderError(f"[avature] {company.name} : {exc}") from None
            batch, page_total = parse_results(resp.text)
            batch_hrefs = {str(row["href"]) for row in batch}
            if page and batch_hrefs and batch_hrefs <= seen_hrefs:
                raise ProviderFormatError(
                    f"[avature] {company.name} : pagination bloquée à l'offset {offset}"
                )
            seen_hrefs.update(batch_hrefs)
            if page == 0:
                if not batch and page_total is None:
                    raise ProviderFormatError(
                        f"[avature] {company.name} : aucune offre ni total dans la page : "
                        "format modifié ?"
                    )
                total = page_total
            rows.extend(batch)
            offset += len(batch)
            if not batch or (total is not None and offset >= total):
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
            url=urljoin(str(company.opt("base_url")), str(href)),
            source=self.name,
            location=str(row.get("location") or ""),
        )
