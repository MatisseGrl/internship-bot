"""Découverte de la plateforme de recrutement d'une entreprise (`--discover`).

Entrées acceptées (une par entreprise) :
- une URL de candidature (« Apply »), éventuellement préfixée d'un nom : `Slack=https://...`.
  C'est la méthode la plus fiable, indispensable pour Workday quand le site a un nom exotique ;
- un simple nom d'entreprise : on essaie des identifiants plausibles (« Scale AI » -> scaleai,
  scale-ai, scale) sur Greenhouse, Ashby, Lever, Workable et SmartRecruiters, puis Workday.

Rien n'est deviné à l'aveugle : une piste n'est retenue que si une vraie requête renvoie des
offres. Un compte qui existe mais ne publie aucune offre est signalé à part (souvent un ancien
compte abandonné après migration vers une autre plateforme).

Particularités Workday utilisées (constatées) : un mauvais tenant ou `wdN` répond HTTP 422,
un bon tenant + `wdN` avec un mauvais site répond 404, et le nom de site est insensible à la casse.
On cherche donc d'abord le `wdN`, puis le site parmi les noms usuels.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import yaml

from internbot.errors import HttpError
from internbot.filters import normalize
from internbot.http import HttpClient

log = logging.getLogger(__name__)

GENERIC_WORDS = {
    "ai", "inc", "labs", "lab", "technologies", "technology", "tech", "networks", "games",
    "group", "corp", "corporation", "company", "co", "hq", "the", "io", "software", "systems",
}  # fmt: skip

WD_ORDER = (
    "wd1", "wd5", "wd3", "wd12", "wd10", "wd103", "wd2", "wd4", "wd6", "wd8",
    "wd101", "wd102", "wd105", "wd108", "wd501", "wd503",
)  # fmt: skip

WD_SITE_TEMPLATES = (
    "External", "External_Career_Site", "ExternalCareerSite", "Careers", "External_Careers",
    "{b}", "{b}Careers", "{b}_Careers", "{b}ExternalCareerSite", "{b}_External_Career_Site",
    "{b}External", "{b}_External", "{b}_Career_Site", "{b}CareerSite", "{b}_Jobs", "{b}Jobs",
    "{b}_External_Careers", "{b}_Ext", "{b}Ext", "External_Site", "ExternalSite", "Ext",
    "external_experienced", "Experienced", "University", "Students", "Early_Careers",
    "Search", "jobs", "careers",
)  # fmt: skip

_LOCALE = re.compile(r"^[a-z]{2}(-[A-Za-z]{2,4})?$")
_PROBE_SITE = "internbot_probe_site"


@dataclass
class Probe:
    provider: str
    options: dict[str, Any]
    jobs: int
    org_name: str | None = None
    exact: bool = True  # identifiant = nom complet (vs variante raccourcie, à vérifier)


@dataclass
class Finding:
    entry: str
    name: str
    probe: Probe | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return self.probe is not None

    def to_config(self) -> dict[str, Any]:
        assert self.probe is not None
        return {"name": self.name, "provider": self.probe.provider, **self.probe.options}


def slug_candidates(name: str) -> list[str]:
    words = normalize(name).split()
    if not words:
        return []
    core = [w for w in words if w not in GENERIC_WORDS] or words
    out: list[str] = []
    for slug in ("".join(words), "-".join(words), "".join(core), "-".join(core)):
        if slug and slug not in out:
            out.append(slug)
    return out


def parse_entry(entry: str) -> tuple[str, str | None]:
    """« Nom=URL » -> (Nom, URL) ; « URL » -> (nom déduit, URL) ; « Nom » -> (Nom, None)."""
    entry = entry.strip()
    if "=" in entry and "://" in entry.split("=", 1)[1]:
        name, url = entry.split("=", 1)
        return name.strip(), url.strip()
    if "://" in entry:
        return "", entry
    return entry, None


def parse_apply_url(url: str) -> tuple[str, dict[str, Any]] | None:
    """Déduit (provider, options) d'une URL de page carrières / candidature."""
    parts = urlsplit(url if "://" in url else f"https://{url}")
    host = (parts.hostname or "").lower()
    segs = [s for s in parts.path.split("/") if s]

    if host.endswith(".myworkdayjobs.com"):
        labels = host.split(".")
        if len(labels) >= 4 and labels[1].startswith("wd"):
            segs = [s for s in segs if not _LOCALE.match(s)]
            if segs:
                return "workday", {"tenant": labels[0], "wd": labels[1], "site": segs[0]}
    if host.endswith(".myworkdaysite.com") and host.split(".")[0].startswith("wd"):
        # https://wd5.myworkdaysite.com/[locale/]recruiting/{tenant}/{site}
        segs = [s for s in segs if not _LOCALE.match(s)]
        if len(segs) >= 3 and segs[0] == "recruiting":
            return "workday", {"tenant": segs[1].lower(), "wd": host.split(".")[0], "site": segs[2]}
    if host.endswith("greenhouse.io") and segs and segs[0] not in ("v1", "embed"):
        return "greenhouse", {"board": segs[0]}
    if host.endswith("greenhouse.io") and "for" in dict(_query(parts.query)):
        return "greenhouse", {"board": dict(_query(parts.query))["for"]}
    if host in ("jobs.lever.co", "jobs.eu.lever.co") and segs:
        opts: dict[str, Any] = {"company": segs[0]}
        if host == "jobs.eu.lever.co":
            opts["region"] = "eu"
        return "lever", opts
    if host == "jobs.ashbyhq.com" and segs:
        return "ashby", {"board": segs[0]}
    if host in ("jobs.smartrecruiters.com", "careers.smartrecruiters.com") and segs:
        return "smartrecruiters", {"company_id": segs[0]}
    if host == "apply.workable.com" and segs and segs[0] not in ("j", "api"):
        return "workable", {"account": segs[0]}
    return None


def _query(q: str) -> Iterable[tuple[str, str]]:
    for pair in q.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            yield k, v


class Discoverer:
    def __init__(self, http: HttpClient) -> None:
        self.http = http

    # -- point d'entrée --------------------------------------------------------------------------

    def discover(self, entry: str) -> Finding:
        name, url = parse_entry(entry)
        if url:
            return self._from_url(name, url, entry)
        return self._from_name(name)

    def _from_url(self, name: str, url: str, entry: str) -> Finding:
        parsed = parse_apply_url(url)
        guessed = name
        if parsed and not guessed:
            first = next(iter(parsed[1].values()))
            guessed = str(first).replace("-", " ").replace("_", " ").title()
        finding = Finding(entry=entry, name=guessed or url)
        if parsed is None:
            finding.notes.append(
                "URL non reconnue (plateforme non supportée : SuccessFactors, Avature, "
                "Eightfold, site maison… -> provider playwright ou alertes e-mail natives)"
            )
            return finding
        provider, opts = parsed
        probe = self._verify(provider, opts)
        if probe and probe.jobs:
            finding.probe = probe
        elif probe:
            finding.notes.append(f"{provider} {opts} existe mais ne publie aucune offre")
        else:
            finding.notes.append(f"{provider} {opts} ne répond pas (identifiant erroné ?)")
        return finding

    def _from_name(self, name: str) -> Finding:
        finding = Finding(entry=name, name=name)
        slugs = slug_candidates(name)
        if not slugs:
            finding.notes.append("nom vide")
            return finding
        hits: list[Probe] = []
        for i, slug in enumerate(slugs):
            for probe_fn in (self._greenhouse, self._ashby, self._lever, self._workable):
                probe = probe_fn(slug)
                if probe is None:
                    continue
                probe.exact = i == 0
                if probe.jobs:
                    hits.append(probe)
                elif probe.provider != "workable":  # Workable répond 200 à beaucoup de noms
                    finding.notes.append(
                        f"{probe.provider} « {slug} » existe mais est vide (compte abandonné ?)"
                    )
        sr = self._smartrecruiters("".join(w.capitalize() for w in normalize(name).split()))
        if sr and sr.jobs:
            hits.append(sr)

        if not hits:
            wd = self._find_workday(name, slugs, finding)
            if wd:
                hits.append(wd)

        if hits:
            # Priorité : identifiant exact, puis nom d'organisation cohérent, puis volume.
            hits.sort(key=lambda p: (p.exact, self._name_matches(name, p), p.jobs), reverse=True)
            finding.probe = hits[0]
            if not hits[0].exact or not self._name_matches(name, hits[0]):
                org = f" (organisation : {hits[0].org_name})" if hits[0].org_name else ""
                finding.notes.append(f"identifiant approché, à vérifier{org}")
            for other in hits[1:]:
                finding.notes.append(
                    f"aussi trouvé : {other.provider} {other.options} ({other.jobs} offres)"
                )
        else:
            finding.notes.append(
                "introuvable sur Greenhouse/Ashby/Lever/Workable/SmartRecruiters/Workday "
                "-> donnez l'URL « Apply » (Nom=URL)"
            )
        return finding

    @staticmethod
    def _name_matches(name: str, probe: Probe) -> bool:
        if not probe.org_name:
            return True
        a, b = normalize(name).replace(" ", ""), normalize(probe.org_name).replace(" ", "")
        return a in b or b in a

    # -- sondes ------------------------------------------------------------------------------------

    def _get(self, url: str, **kw: Any) -> Any:
        try:
            return self.http.get_json(url, **kw)
        except HttpError as exc:
            if exc.status not in (404, 410, 422, None):
                log.debug("Sonde %s : %s", url, exc)
            return None

    def _verify(self, provider: str, opts: dict[str, Any]) -> Probe | None:
        if provider == "workday":
            total = self._workday_total(opts["tenant"], opts["wd"], opts["site"])
            return Probe("workday", opts, total) if total is not None else None
        if provider == "lever":
            return self._lever(opts["company"], region=opts.get("region", "global"))
        fn: dict[str, Callable[[str], Probe | None]] = {
            "greenhouse": self._greenhouse,
            "ashby": self._ashby,
            "workable": self._workable,
            "smartrecruiters": self._smartrecruiters,
        }
        return fn[provider](next(iter(opts.values())))

    def _greenhouse(self, board: str) -> Probe | None:
        data = self._get(
            f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs", params={"content": "false"}
        )
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            return None
        jobs = data["jobs"]
        org = jobs[0].get("company_name") if jobs and isinstance(jobs[0], dict) else None
        return Probe("greenhouse", {"board": board}, len(jobs), org)

    def _ashby(self, board: str) -> Probe | None:
        data = self._get(f"https://api.ashbyhq.com/posting-api/job-board/{board}")
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            return None
        listed = [j for j in data["jobs"] if isinstance(j, dict) and j.get("isListed", True)]
        return Probe("ashby", {"board": board}, len(listed))

    def _lever(self, company: str, *, region: str = "global") -> Probe | None:
        host = "https://api.eu.lever.co" if region == "eu" else "https://api.lever.co"
        data = self._get(f"{host}/v0/postings/{company}", params={"mode": "json"})
        if not isinstance(data, list):
            if region == "global":
                return self._lever(company, region="eu")
            return None
        opts: dict[str, Any] = {"company": company}
        if region == "eu":
            opts["region"] = "eu"
        return Probe("lever", opts, len(data))

    def _workable(self, account: str) -> Probe | None:
        data = self._get(f"https://apply.workable.com/api/v1/widget/accounts/{account}")
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            return None
        return Probe("workable", {"account": account}, len(data["jobs"]), data.get("name"))

    def _smartrecruiters(self, company_id: str) -> Probe | None:
        if not company_id:
            return None
        data = self._get(
            f"https://api.smartrecruiters.com/v1/companies/{company_id}/postings",
            params={"limit": 1},
        )
        if not isinstance(data, dict) or not isinstance(data.get("totalFound"), int):
            return None
        content = data.get("content") or []
        org = None
        if content and isinstance(content[0], dict):
            org = (content[0].get("company") or {}).get("name")
        return Probe("smartrecruiters", {"company_id": company_id}, data["totalFound"], org)

    # -- Workday -----------------------------------------------------------------------------------

    def _workday_status(self, tenant: str, wd: str, site: str) -> tuple[int | None, int]:
        """Retourne (statut HTTP, total d'offres)."""
        url = f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
        body = {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}
        try:
            data = self.http.post_json(url, body)
        except HttpError as exc:
            return exc.status, 0
        total = data.get("total") if isinstance(data, dict) else None
        return 200, int(total or 0)

    def _workday_total(self, tenant: str, wd: str, site: str) -> int | None:
        status, total = self._workday_status(tenant.lower(), wd, site)
        return total if status == 200 else None

    def _find_workday(self, name: str, slugs: list[str], finding: Finding) -> Probe | None:
        tenants = [s for s in slugs if "-" not in s]
        for tenant in tenants:
            wd = self._find_workday_wd(tenant)
            if wd is None:
                continue
            log.info("  Workday : tenant « %s » trouvé sur %s, recherche du site…", tenant, wd)
            for site in self._site_candidates(tenant, name):
                status, total = self._workday_status(tenant, wd, site)
                if status == 200:
                    return Probe(
                        "workday", {"tenant": tenant, "wd": wd, "site": site}, total,
                        exact=tenant == slugs[0],
                    )  # fmt: skip
            finding.notes.append(
                f"Workday : tenant « {tenant} » trouvé sur {wd}, seul le nom du site manque "
                f"(URL Apply : https://{tenant}.{wd}.myworkdayjobs.com/<site>/...)"
            )
        return None

    def _find_workday_wd(self, tenant: str) -> str | None:
        for wd in WD_ORDER:
            status, _ = self._workday_status(tenant, wd, _PROBE_SITE)
            if status in (404, 200):  # 404 = bon tenant + bon wd, site inconnu (attendu)
                return wd
        return None

    @staticmethod
    def _site_candidates(tenant: str, name: str) -> list[str]:
        words = normalize(name).split()
        # Le site est insensible à la casse : la 1re graphie rencontrée sert juste à l'affichage.
        bases = [
            "".join(w.capitalize() for w in words),
            "".join(words).upper(),
            "_".join(w.capitalize() for w in words),  # ex: Capital_One
            tenant,
        ]
        out: list[str] = []
        seen: set[str] = set()
        for template in WD_SITE_TEMPLATES:
            for base in bases if "{b}" in template else [""]:
                site = template.format(b=base)
                if site.lower() not in seen:
                    seen.add(site.lower())
                    out.append(site)
        return out


def run_discovery(entries: Iterable[str], http: HttpClient) -> list[Finding]:
    discoverer = Discoverer(http)
    findings = []
    for entry in entries:
        entry = entry.strip()
        if not entry or entry.startswith("#"):
            continue
        log.info("Découverte : %s", entry)
        finding = discoverer.discover(entry)
        if finding.probe:
            p = finding.probe
            log.info("  ✓ %s %s — %d offres", p.provider, p.options, p.jobs)
        else:
            log.info("  ✗ %s", "; ".join(finding.notes))
        findings.append(finding)
    return findings


def render_report(findings: list[Finding]) -> str:
    """Bloc YAML prêt à coller sous `companies:` + entreprises non trouvées en commentaire."""
    lines = [
        "# --- Généré par `internbot --discover` : vérifiez les lignes marquées « à vérifier ».",
        "",
    ]
    for f in findings:
        if not f.found:
            continue
        block = yaml.safe_dump([f.to_config()], allow_unicode=True, sort_keys=False).rstrip()
        assert f.probe is not None
        comment = f"  # {f.probe.jobs} offres"
        if f.notes:
            comment += " — " + "; ".join(f.notes)
        first, *rest = block.splitlines()
        lines.append(first + comment)
        lines.extend(rest)
    missing = [f for f in findings if not f.found]
    if missing:
        lines += ["", "# --- Non trouvées automatiquement :"]
        for f in missing:
            lines.append(f"# - {f.name} : {'; '.join(f.notes)}")
    return "\n".join(lines) + "\n"
