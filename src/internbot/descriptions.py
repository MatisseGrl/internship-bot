"""Texte complet d'une offre, pour la notation (grille de `notation/GRILLE.md`).

La grille juge les MISSIONS décrites dans l'offre, pas le titre : il faut donc le texte de
l'annonce. Une source par plateforme, la plus fiable possible :

- Greenhouse, SmartRecruiters, Oracle HCM, Eightfold (v2) : API publique de détail de l'offre
  (celle qu'appelle le site carrières lui-même) ;
- Apple : données embarquées dans la page de l'offre (`jobDetails`) ;
- toutes les autres (Workday, Ashby, Lever, sitemaps, Avature, Gestmax…) : la page publique
  de l'offre, en lisant d'abord le JSON-LD `JobPosting` (description structurée publiée pour
  les moteurs de recherche), sinon le texte visible de la page.

Aucun contournement : une page protégée (anti-bot, connexion) lève `DescriptionError`, et
l'offre est gardée « illisible » pour un tri à la main.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

from internbot.config import CompanyConfig
from internbot.errors import HttpError, InternbotError
from internbot.http import HttpClient
from internbot.models import Job

# En dessous, le texte récupéré n'est pas une annonce (page vide, bandeau cookies, challenge
# anti-bot…) : on ne note pas sur si peu.
MIN_CHARS = 400

_LD_JSON = re.compile(
    r"<script\b[^>]*\btype=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.S | re.I
)
_APPLE_DATA = re.compile(
    r"window\.__staticRouterHydrationData\s*=\s*JSON\.parse\((\".*?\")\);", re.S
)
_GH_ID = re.compile(r"(?:gh_jid=|/jobs/)(\d+)")
_EIGHTFOLD_ID = re.compile(r"/careers/job/(\d+)")


class DescriptionError(InternbotError):
    """Texte de l'offre impossible à lire (page protégée, offre fermée, format inconnu)."""


@dataclass(frozen=True)
class Description:
    text: str
    source: str  # ex. « api greenhouse », « json-ld », « page »


# -- HTML -> texte -----------------------------------------------------------------------------

_SKIP = {"script", "style", "noscript", "svg", "head", "template", "iframe", "button", "form"}
_CHROME = {"nav", "header", "footer", "aside"}
_BLOCK = {
    "p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table",
    "section", "article", "dd", "dt", "blockquote", "pre", "hr",
}  # fmt: skip
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "wbr"}


class _TextExtractor(HTMLParser):
    def __init__(self, *, skip_chrome: bool) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = _SKIP | (_CHROME if skip_chrome else set())
        self.skipping: list[str] = []
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.skipping:
            if tag == self.skipping[-1] and tag not in _VOID:
                self.skipping.append(tag)
            return
        if tag in self.skip and tag not in _VOID:
            self.skipping.append(tag)
        elif tag in _BLOCK:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")

    def handle_endtag(self, tag: str) -> None:
        if self.skipping:
            if tag == self.skipping[-1]:
                self.skipping.pop()
            return
        if tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skipping:
            self.parts.append(data)


def html_to_text(fragment: str, *, skip_chrome: bool = False) -> str:
    """Texte lisible d'un fragment HTML : un paragraphe par ligne, espaces normalisés."""
    parser = _TextExtractor(skip_chrome=skip_chrome)
    parser.feed(fragment)
    parser.close()
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    out: list[str] = []
    for line in lines:
        if line and line != "-" and (not out or out[-1] != line):
            out.append(line)
    return "\n".join(out)


def _rich(value: Any) -> str:
    """Champ texte d'une API : HTML (parfois échappé deux fois) -> texte brut."""
    text = str(value or "")
    if "&lt;" in text:
        text = html.unescape(text)
    return html_to_text(text) if "<" in text else " ".join(text.split())


# -- JSON-LD -----------------------------------------------------------------------------------


def _ld_nodes(data: Any) -> Iterator[Mapping[str, Any]]:
    if isinstance(data, list):
        for item in data:
            yield from _ld_nodes(item)
    elif isinstance(data, dict):
        yield data
        yield from _ld_nodes(data.get("@graph"))


def jobposting_text(page: str) -> str | None:
    """Description du JSON-LD `JobPosting` d'une page, avec titre, lieu, dates et contrat."""
    for raw in _LD_JSON.findall(page):
        try:
            data = json.loads(raw.strip())
        except ValueError:
            continue
        for node in _ld_nodes(data):
            kind = node.get("@type")
            kinds = kind if isinstance(kind, list) else [kind]
            if "JobPosting" not in kinds or not node.get("description"):
                continue
            header = [
                f"{label} : {_ld_value(node.get(key))}"
                for label, key in (
                    ("Intitulé", "title"),
                    ("Lieu", "jobLocation"),
                    ("Type de contrat", "employmentType"),
                    ("Publiée le", "datePosted"),
                    ("Valable jusqu'au", "validThrough"),
                )
                if _ld_value(node.get(key))
            ]
            return "\n".join([*header, _rich(node["description"])])
    return None


def _ld_value(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, list):
        return " · ".join(v for v in (_ld_value(x) for x in value) if v)
    if isinstance(value, dict):
        address = value.get("address")
        if isinstance(address, dict):
            parts = (address.get(k) for k in ("addressLocality", "addressRegion", "addressCountry"))
            return ", ".join(str(p) for p in parts if p and not isinstance(p, dict))
        return str(value.get("name") or "")
    return " ".join(str(value).split())


# -- par plateforme ----------------------------------------------------------------------------


class DescriptionFetcher:
    """Récupère le texte d'une offre via le client HTTP poli (délai par domaine, retries)."""

    def __init__(self, http: HttpClient, companies: Mapping[str, CompanyConfig]) -> None:
        self.http = http
        self.companies = companies

    def fetch(self, job: Job) -> Description:
        company = self.companies.get(job.company)
        if company is None:
            raise DescriptionError(f"entreprise absente de la config : {job.company}")
        method = getattr(self, f"_{company.provider}", self._page)
        try:
            description: Description = method(company, job)
        except HttpError as exc:
            raise DescriptionError(str(exc)) from None
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise DescriptionError(f"format inattendu ({type(exc).__name__}: {exc})") from None
        if len(description.text) < MIN_CHARS:
            raise DescriptionError(
                f"texte trop court ({len(description.text)} caractères, source "
                f"{description.source}) : page protégée ou offre fermée ?"
            )
        return description

    def _greenhouse(self, company: CompanyConfig, job: Job) -> Description:
        match = _GH_ID.search(job.url) or _GH_ID.search(f"/jobs/{job.job_id}")
        if not match:
            raise DescriptionError(f"identifiant Greenhouse introuvable : {job.url}")
        board = company.opt("board")
        data = self.http.get_json(
            f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{match.group(1)}"
        )
        location = (data.get("location") or {}).get("name") or ""
        text = "\n".join(
            x for x in (f"Intitulé : {data.get('title', '')}", f"Lieu : {location}") if x
        )
        return Description(f"{text}\n{_rich(data.get('content'))}", "api greenhouse")

    def _smartrecruiters(self, company: CompanyConfig, job: Job) -> Description:
        cid = company.opt("company_id")
        data = self.http.get_json(
            f"https://api.smartrecruiters.com/v1/companies/{cid}/postings/{job.job_id}"
        )
        sections = (data.get("jobAd") or {}).get("sections") or {}
        parts = [f"Intitulé : {data.get('name', '')}"]
        loc = data.get("location") or {}
        parts.append("Lieu : " + ", ".join(str(loc[k]) for k in ("city", "country") if loc.get(k)))
        type_ = (data.get("typeOfEmployment") or {}).get("label")
        if type_:
            parts.append(f"Type de contrat : {type_}")
        for key in ("jobDescription", "qualifications", "additionalInformation"):
            section = sections.get(key) or {}
            if section.get("text"):
                parts.append(f"{section.get('title') or key}\n{_rich(section['text'])}")
        return Description("\n".join(parts), "api smartrecruiters")

    def _oracle_hcm(self, company: CompanyConfig, job: Job) -> Description:
        host, site = company.opt("host"), company.opt("site")
        url = (
            f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
            f'?expand=all&onlyData=true&finder=ById;Id="{job.job_id}",siteNumber={site}'
        )
        item = self.http.get_json(url)["items"][0]
        parts = [f"Intitulé : {item.get('Title', '')}", f"Lieu : {item.get('PrimaryLocation')}"]
        for key in (
            "ExternalDescriptionStr",
            "ExternalResponsibilitiesStr",
            "ExternalQualificationsStr",
            "OrganizationDescriptionStr",
        ):
            if item.get(key):
                parts.append(_rich(item[key]))
        return Description("\n".join(parts), "api oracle")

    def _eightfold(self, company: CompanyConfig, job: Job) -> Description:
        match = _EIGHTFOLD_ID.search(job.url)
        if company.opt("api", "v2") == "v2" and match:
            data = self.http.get_json(
                f"https://{company.opt('host')}/api/apply/v2/jobs/{match.group(1)}",
                params={"domain": company.opt("domain")},
            )
            if data.get("job_description"):
                parts = [
                    f"Intitulé : {data.get('posting_name') or data.get('name', '')}",
                    f"Lieu : {' · '.join(data.get('locations') or [])}",
                    _rich(data["job_description"]),
                ]
                return Description("\n".join(parts), "api eightfold")
        return self._page(company, job)

    def _apple(self, company: CompanyConfig, job: Job) -> Description:
        page = self.http.request("GET", job.url, headers={"Accept": "text/html"}).text
        match = _APPLE_DATA.search(page)
        if not match:
            raise DescriptionError("données de la page Apple introuvables")
        details = json.loads(json.loads(match.group(1)))["loaderData"]["jobDetails"]["jobsData"]
        parts = [f"Intitulé : {details.get('postingTitle', '')}"]
        locations = [
            str(loc.get("name")) for loc in details.get("locations") or [] if isinstance(loc, dict)
        ]
        if locations:
            parts.append(f"Lieu : {' · '.join(locations)}")
        for key, label in (
            ("jobSummary", "Résumé"),
            ("description", "Description"),
            ("responsibilities", "Responsabilités"),
            ("minimumQualifications", "Qualifications minimales"),
            ("preferredQualifications", "Qualifications souhaitées"),
            ("educationAndExperience", "Formation"),
        ):
            if details.get(key):
                parts.append(f"{label}\n{_rich(details[key])}")
        return Description("\n".join(parts), "page apple")

    def _page(self, company: CompanyConfig, job: Job) -> Description:
        page = self.http.request("GET", job.url, headers={"Accept": "text/html"}).text
        text = jobposting_text(page)
        if text and len(text) >= MIN_CHARS:
            return Description(text, "json-ld")
        return Description(html_to_text(page, skip_chrome=True), "page")
