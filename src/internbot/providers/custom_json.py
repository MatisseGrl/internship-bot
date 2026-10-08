"""Provider générique pour les sites carrières « maison » qui appellent leur propre endpoint JSON
(Amazon, Atlassian, IBM…). Tout se décrit dans config.yaml, sans code :

    - name: Amazon
      provider: custom_json
      url: https://www.amazon.jobs/en/search.json
      method: GET                     # GET (défaut) ou POST
      params: {base_query: intern, result_limit: "{limit}", offset: "{offset}"}
      body: {...}                     # corps JSON (POST)
      headers: {...}                  # en-têtes supplémentaires (jamais de secret)
      items_path: jobs                # chemin pointé vers la liste d'offres (`data.positions`…)
      total_path: hits                # optionnel : nombre total d'offres
      page_size: 100                  # active la pagination (placeholders ci-dessous)
      max_pages: 20                   # borne de sécurité (défaut 20)
      fields:
        id: id_icims                  # chemin pointé dans une offre
        title: title
        url: "https://www.amazon.jobs{job_path}"   # gabarit : {chemin} remplacé
        location: [city, country_code]             # un chemin, un gabarit ou une liste
        date: posted_date             # ISO, epoch (s ou ms), « October 8, 2026 »…

Placeholders utilisables dans `url`, `params` et `body` : `{offset}` (index de la 1re offre),
`{page}` (numéro de page à partir de 1), `{page0}` (à partir de 0), `{limit}` (= page_size).
Une valeur réduite à un seul placeholder (« {offset} ») est envoyée comme un entier.
Sans placeholder, une seule requête est faite.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Any

from internbot.errors import HttpError, ProviderError, ProviderFormatError
from internbot.models import Job
from internbot.providers.base import (
    Provider,
    epoch_date,
    get_path,
    iso_date,
    join_locations,
    parse_items,
    register,
)

if TYPE_CHECKING:
    from internbot.config import CompanyConfig

log = logging.getLogger(__name__)

_PLACEHOLDER = re.compile(r"\{(offset|page0|page|limit)\}")
_TEMPLATE = re.compile(r"\{([^{}]+)\}")
_DATE_FORMATS = ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y", "%m/%d/%Y", "%Y-%m-%d")


def substitute(value: Any, variables: Mapping[str, int]) -> Any:
    """Remplace récursivement {offset}/{page}/{page0}/{limit} dans chaînes, listes et dicts."""
    if isinstance(value, str):
        whole = _PLACEHOLDER.fullmatch(value)
        if whole:
            return variables[whole.group(1)]
        return _PLACEHOLDER.sub(lambda m: str(variables[m.group(1)]), value)
    if isinstance(value, list):
        return [substitute(v, variables) for v in value]
    if isinstance(value, dict):
        return {k: substitute(v, variables) for k, v in value.items()}
    return value


def page_variables(page: int, page_size: int) -> dict[str, int]:
    """Valeurs des placeholders pour la page `page` (numérotée à partir de 0)."""
    return {"offset": page * page_size, "page": page + 1, "page0": page, "limit": page_size}


def has_placeholder(*values: Any) -> bool:
    return any(_PLACEHOLDER.search(str(v)) for v in values if v)


def render_field(item: Mapping[str, Any], spec: Any) -> Any:
    """`spec` = chemin pointé, gabarit « https://x{path} », ou liste des deux."""
    if spec is None:
        return None
    if isinstance(spec, list):
        return [render_field(item, s) for s in spec]
    spec = str(spec)
    if "{" in spec:

        def repl(m: re.Match[str]) -> str:
            value = get_path(item, m.group(1))
            if value in (None, "") or isinstance(value, dict | list):
                raise ValueError(f"champ '{m.group(1)}' absent pour le gabarit {spec!r}")
            return str(value)

        return _TEMPLATE.sub(repl, spec)
    return get_path(item, spec)


def parse_date(value: Any) -> str | None:
    """Date dans les formats rencontrés sur les sites maison -> 'YYYY-MM-DD' (sinon tel quel)."""
    if value in (None, ""):
        return None
    if isinstance(value, int | float) or (isinstance(value, str) and value.strip().isdigit()):
        return epoch_date(value)
    text = " ".join(str(value).split())
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    try:
        return parsedate_to_datetime(text).date().isoformat()  # RFC 2822 (flux RSS)
    except (TypeError, ValueError, IndexError):
        return iso_date(text)


def _flatten(value: Any) -> list[Any]:
    if isinstance(value, list | tuple):
        return [x for v in value for x in _flatten(v)]
    return [] if value is None or isinstance(value, dict) else [value]


@register
class CustomJsonProvider(Provider):
    name = "custom_json"
    required_fields = ("url", "items_path", "fields")
    optional_fields = (
        "method",
        "params",
        "body",
        "headers",
        "total_path",
        "page_size",
        "max_pages",
    )

    def fetch_jobs(self, company: CompanyConfig) -> list[Job]:
        fields = company.opt("fields") or {}
        missing = [f for f in ("id", "title", "url") if not fields.get(f)]
        if missing:
            raise ProviderError(
                f"[custom_json] {company.name} : fields.{', fields.'.join(missing)} manquant(s)"
            )
        items = self.fetch_items(company)
        return parse_items(items, lambda it: self._parse(company, fields, it), provider=self.name)

    def fetch_items(self, company: CompanyConfig) -> list[Any]:
        url = str(company.opt("url"))
        method = str(company.opt("method", "GET")).upper()
        params, body = company.opt("params"), company.opt("body")
        headers = company.opt("headers")
        page_size = int(company.opt("page_size") or 0)
        paginated = page_size > 0 and has_placeholder(url, params, body)
        max_pages = int(company.opt("max_pages", 20)) if paginated else 1
        items_path, total_path = str(company.opt("items_path")), company.opt("total_path")

        items: list[Any] = []
        total: int | None = None
        for page in range(max_pages):
            variables = page_variables(page, page_size)
            try:
                data = self._call(
                    method,
                    substitute(url, variables),
                    substitute(params, variables),
                    substitute(body, variables),
                    headers,
                )
            except HttpError as exc:
                raise ProviderError(f"[custom_json] {company.name} : {exc}") from None
            batch = get_path(data, items_path)
            if not isinstance(batch, list):
                raise ProviderFormatError(
                    f"[custom_json] {company.name} : '{items_path}' n'est pas une liste "
                    f"(reçu {type(batch).__name__}) : format modifié ?"
                )
            if total is None and total_path:
                try:
                    total = int(get_path(data, str(total_path)) or 0)
                except (TypeError, ValueError):
                    total = None
            items.extend(batch)
            if (
                not paginated
                or not batch
                or len(batch) < page_size
                or (total is not None and len(items) >= total)
            ):
                break
        else:
            if paginated:
                log.warning(
                    "[custom_json] %s : limite de %d pages atteinte (%d/%s offres)",
                    company.name,
                    max_pages,
                    len(items),
                    total,
                )
        return items

    def _call(
        self,
        method: str,
        url: str,
        params: Any,
        body: Any,
        headers: Mapping[str, str] | None,
    ) -> Any:
        if method == "POST":
            if params:
                raise ProviderError("[custom_json] `params` en POST : mettez-les dans l'URL")
            return self.http.post_json(url, body or {}, headers=headers)
        if method != "GET":
            raise ProviderError(f"[custom_json] méthode non supportée : {method}")
        return self.http.get_json(url, params=params, headers=headers)

    def _parse(
        self, company: CompanyConfig, fields: Mapping[str, Any], item: dict[str, Any]
    ) -> Job | None:
        job_id = render_field(item, fields["id"])
        title = render_field(item, fields["title"])
        url = render_field(item, fields["url"])
        if job_id in (None, "") or not title or not url:
            return None
        location = render_field(item, fields.get("location"))
        return Job(
            company=company.name,
            job_id=str(job_id),
            title=" ".join(str(title).split()),
            url=str(url),
            source=self.name,
            location=join_locations(*_flatten(location)),
            posted_at=parse_date(render_field(item, fields.get("date"))),
        )
