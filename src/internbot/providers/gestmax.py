"""Offres publiques Gestmax, affichées côté serveur (MBDA France).

La page ``/search/index`` affiche 20 offres et le nombre total. Les pages suivantes
sont accessibles à ``/search/index/page/N``. Aucune session ni JavaScript requis.
"""

from __future__ import annotations

import html
import logging
import re
from contextlib import suppress
from datetime import datetime
from typing import TYPE_CHECKING
from urllib.parse import urljoin

from internbot.errors import HttpError, ProviderError, ProviderFormatError
from internbot.models import Job
from internbot.providers.base import Provider, register

if TYPE_CHECKING:
    from internbot.config import CompanyConfig

log = logging.getLogger(__name__)

_ROW = re.compile(r"<tr\b[^>]*\bvacancy-id-(\d+)[^>]*>(.*?)</tr>", re.I | re.S)
_CELL = re.compile(r'<td\b[^>]*\bheaders="([^"]+)"[^>]*>(.*?)</td>', re.I | re.S)
_LINK = re.compile(r'<a\b[^>]*\bhref="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
_TOTAL = re.compile(r'<strong\s+id="pager-total-results">\s*(\d+)\s*</strong>', re.I)
_TAGS = re.compile(r"<[^>]+>")


def _text(fragment: str) -> str:
    return " ".join(html.unescape(_TAGS.sub(" ", fragment)).split())


def parse_results(page: str) -> tuple[list[dict[str, str]], int | None]:
    """Lit les lignes du tableau et son total, sans supposer que tous les postes sont des stages."""
    rows: list[dict[str, str]] = []
    for match in _ROW.finditer(page):
        cells = {key: value for key, value in _CELL.findall(match.group(2))}
        title_link = _LINK.search(cells.get("vacancy_title", ""))
        if not title_link:
            continue
        location_link = _LINK.search(cells.get("vac_localisation", ""))
        date_link = _LINK.search(cells.get("vacancy_activation_date", ""))
        rows.append(
            {
                "id": match.group(1),
                "url": html.unescape(title_link.group(1)),
                "title": _text(title_link.group(2)),
                "location": _text(location_link.group(2)) if location_link else "",
                "date": _text(date_link.group(2)) if date_link else "",
            }
        )
    total = _TOTAL.search(page)
    return rows, int(total.group(1)) if total else None


@register
class GestmaxProvider(Provider):
    name = "gestmax"
    required_fields = ("base_url",)
    optional_fields = ("max_pages",)

    def fetch_jobs(self, company: CompanyConfig) -> list[Job]:
        base = str(company.opt("base_url")).rstrip("/")
        max_pages = int(company.opt("max_pages", 50))
        if max_pages < 1:
            raise ProviderError(f"[gestmax] {company.name} : max_pages doit être positif")
        jobs: list[Job] = []
        seen: set[str] = set()
        total: int | None = None
        for page_number in range(1, max_pages + 1):
            path = "/search/index" if page_number == 1 else f"/search/index/page/{page_number}"
            try:
                response = self.http.request("GET", f"{base}{path}")
            except HttpError as exc:
                raise ProviderError(f"[gestmax] {company.name} : {exc}") from None
            rows, page_total = parse_results(response.text)
            if page_number == 1:
                if page_total is None:
                    raise ProviderFormatError(
                        f"[gestmax] {company.name} : total absent, format modifié ?"
                    )
                total = page_total
                if total and not rows:
                    raise ProviderFormatError(
                        f"[gestmax] {company.name} : aucune offre lisible, format modifié ?"
                    )
            elif rows and all(row["id"] in seen for row in rows):
                raise ProviderFormatError(
                    f"[gestmax] {company.name} : pagination bloquée à la page {page_number}"
                )
            elif not rows and total is not None and len(seen) < total:
                raise ProviderFormatError(
                    f"[gestmax] {company.name} : page {page_number} vide avant la fin "
                    f"({len(seen)}/{total} offres)"
                )
            for row in rows:
                if row["id"] in seen or not row["title"]:
                    continue
                seen.add(row["id"])
                date = None
                with suppress(ValueError):
                    date = datetime.strptime(row["date"], "%d/%m/%Y").date().isoformat()
                jobs.append(
                    Job(
                        company=company.name,
                        job_id=row["id"],
                        title=row["title"],
                        url=urljoin(base, row["url"]),
                        source=self.name,
                        location=row["location"],
                        posted_at=date,
                    )
                )
            if not rows or (total is not None and len(seen) >= total):
                break
        else:
            log.warning(
                "[gestmax] %s : limite de %d pages atteinte (%d/%s offres)",
                company.name,
                max_pages,
                len(jobs),
                total,
            )
        return jobs
