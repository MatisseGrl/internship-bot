"""Provider générique Playwright — DERNIER RECOURS pour un site sans API JSON.

Installation : pip install -e ".[playwright]" && playwright install chromium

Configuration :
    - name: MaBoite
      provider: playwright
      url: https://exemple.com/careers
      item_selector: "li.job"          # un élément par offre
      title_selector: "h3"             # relatif à l'élément (défaut : texte du lien)
      link_selector: "a"               # relatif à l'élément (défaut : "a")
      location_selector: ".location"   # optionnel
      wait_for: "li.job"               # optionnel : sélecteur à attendre

Une seule page chargée par run, pas de clics automatisés, pas de contournement anti-bot :
si le site affiche un CAPTCHA, ce provider échoue proprement.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

from internbot.errors import ProviderError
from internbot.models import Job
from internbot.providers.base import Provider, register

if TYPE_CHECKING:
    from internbot.config import CompanyConfig


@register
class PlaywrightGenericProvider(Provider):
    name = "playwright"
    required_fields = ("url", "item_selector")
    optional_fields = ("title_selector", "link_selector", "location_selector", "wait_for")

    def fetch_jobs(self, company: CompanyConfig) -> list[Job]:
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise ProviderError(
                "[playwright] Playwright n'est pas installé : "
                "pip install -e '.[playwright]' && playwright install chromium"
            ) from None

        url = str(company.opt("url"))
        user_agent = str(self.http.session.headers.get("User-Agent", ""))
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                try:
                    page = browser.new_page(user_agent=user_agent)
                    page.goto(url, timeout=int(self.http.timeout_s * 1000) * 2)
                    page.wait_for_selector(
                        company.opt("wait_for") or company.opt("item_selector"), timeout=20_000
                    )
                    rows = page.eval_on_selector_all(
                        company.opt("item_selector"),
                        _EXTRACT_JS,
                        {
                            "title": company.opt("title_selector"),
                            "link": company.opt("link_selector", "a"),
                            "location": company.opt("location_selector"),
                        },
                    )
                finally:
                    browser.close()
        except PlaywrightError as exc:
            raise ProviderError(f"[playwright] {company.name} : {exc}") from None
        return rows_to_jobs(company, url, rows)


def rows_to_jobs(company: CompanyConfig, page_url: str, rows: list[dict[str, Any]]) -> list[Job]:
    jobs: dict[str, Job] = {}
    for row in rows:
        href, title = row.get("href"), (row.get("title") or "").strip()
        if not href or not title:
            continue
        absolute = urljoin(page_url, href)
        jobs[absolute] = Job(
            company=company.name,
            job_id=absolute,  # l'URL est l'identifiant le plus stable dont on dispose
            title=" ".join(title.split()),
            url=absolute,
            source="playwright",
            location=" ".join((row.get("location") or "").split()),
        )
    return list(jobs.values())


_EXTRACT_JS = """
(items, sel) => items.map(el => {
  const link = sel.link ? el.querySelector(sel.link) : null;
  const a = link || (el.tagName === 'A' ? el : el.querySelector('a'));
  const t = sel.title ? el.querySelector(sel.title) : a;
  const l = sel.location ? el.querySelector(sel.location) : null;
  return {
    href: a ? a.getAttribute('href') : null,
    title: t ? t.textContent : (a ? a.textContent : ''),
    location: l ? l.textContent : ''
  };
})
"""
