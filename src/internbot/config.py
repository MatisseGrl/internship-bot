"""Chargement et validation de config.yaml."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from internbot.errors import ConfigError
from internbot.http import DEFAULT_USER_AGENT

log = logging.getLogger(__name__)


Region = Literal["us", "canada", "uk", "europe", "asia", "australia", "israel", "japan", "uae"]
DEFAULT_REGIONS: tuple[Region, ...] = ("us", "canada", "uk", "europe", "asia", "australia")

# Clés de l'ancien filtre, remplacées par les listes du filtre v3 (filters_v3.py). Encore
# acceptées pour qu'une ancienne config se charge, mais ignorées avec un avertissement.
OBSOLETE_FILTER_KEYS = ("title_include", "keywords_any", "locations_include", "locations_exclude")


class FiltersConfig(BaseModel):
    """Réglages du filtre v3 (listes de mots dans filters_v3.py) + exclusions propres à Matisse.

    Matching insensible à la casse/aux accents, par mots entiers."""

    model_config = ConfigDict(extra="forbid")

    # Zones où une offre est notifiée (voir filters_v3.LOCATIONS). Remote/hybrid toujours gardé.
    regions: list[Region] = Field(default_factory=lambda: list(DEFAULT_REGIONS))
    include_data: bool = True
    include_fde: bool = True  # forward deployed / solutions / customer engineer
    include_quant_research: bool = False  # quant research pur (trader, QR)
    # Appliqués AVANT le filtre v3 : un titre qui contient un de ces mots est écarté.
    title_exclude: list[str] = Field(
        default_factory=lambda: ["senior", "staff", "principal", "manager", "director"]
    )
    year_hint: list[str] = Field(default_factory=list)
    # prefer  : rejette un titre qui mentionne UNIQUEMENT une autre année (ex: « Summer 2026 »),
    #           garde les titres sans année.
    # require : le titre doit contenir une des années de year_hint.
    # off     : year_hint ignoré.
    year_hint_mode: Literal["prefer", "require", "off"] = "prefer"

    @model_validator(mode="before")
    @classmethod
    def _drop_obsolete_keys(cls, data: Any) -> Any:
        if isinstance(data, dict) and (found := [k for k in OBSOLETE_FILTER_KEYS if k in data]):
            log.warning(
                "filters : %s ignoré(s) depuis le filtre v3 (voir README › Filtres)",
                ", ".join(found),
            )
            data = {k: v for k, v in data.items() if k not in OBSOLETE_FILTER_KEYS}
        return data


class NotifierConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["telegram", "console"] = "telegram"
    # Au-delà de ce nombre de nouvelles offres dans un run, on envoie des messages groupés.
    group_threshold: int = Field(default=10, ge=1)
    disable_link_preview: bool = True


class HttpConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_agent: str = DEFAULT_USER_AGENT
    timeout_s: float = Field(default=20.0, gt=0)
    min_delay_s: float = Field(default=1.5, ge=1.0)
    max_retries: int = Field(default=3, ge=0, le=6)
    backoff_base_s: float = Field(default=2.0, ge=0.5)


class AlertsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Alerte Telegram quand une entreprise échoue N runs d'affilée (0 = désactivé).
    failure_threshold: int = Field(default=3, ge=0)
    log_removed: bool = True


class DigestConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    every_days: int = Field(default=7, ge=1)


class CompanyConfig(BaseModel):
    """Une entreprise surveillée. Les champs propres au provider (tenant, board...) sont libres
    ici et validés ensuite contre la déclaration du provider."""

    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    enabled: bool = True
    filters: dict[str, Any] | None = None

    @field_validator("name", "provider")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("ne doit pas être vide")
        return value

    @property
    def options(self) -> dict[str, Any]:
        return dict(self.model_extra or {})

    def opt(self, key: str, default: Any = None) -> Any:
        return self.options.get(key, default)


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notifier: NotifierConfig = Field(default_factory=NotifierConfig)
    filters: FiltersConfig = Field(default_factory=FiltersConfig)
    http: HttpConfig = Field(default_factory=HttpConfig)
    alerts: AlertsConfig = Field(default_factory=AlertsConfig)
    digest: DigestConfig = Field(default_factory=DigestConfig)
    companies: list[CompanyConfig] = Field(min_length=1)

    def filters_for(self, company: CompanyConfig) -> FiltersConfig:
        """Filtres globaux, éventuellement surchargés champ par champ au niveau de l'entreprise."""
        if not company.filters:
            return self.filters
        return FiltersConfig(**{**self.filters.model_dump(), **company.filters})


def load_config(path: str | Path) -> AppConfig:
    path = Path(path)
    if not path.is_file():
        raise ConfigError(
            f"Fichier de configuration introuvable : {path}. "
            "Copiez config.example.yaml en config.yaml."
        )
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML invalide dans {path} : {exc}") from None
    if not isinstance(raw, dict):
        raise ConfigError(
            f"{path} doit contenir un objet YAML (clés notifier, filters, companies…)"
        )
    return parse_config(raw, source=str(path))


def parse_config(raw: dict[str, Any], *, source: str = "config") -> AppConfig:
    try:
        cfg = AppConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(exc, raw, source)) from None
    _validate_companies(cfg, source)
    return cfg


def _validate_companies(cfg: AppConfig, source: str) -> None:
    # Import local : providers -> config (TYPE_CHECKING) ; évite l'import circulaire.
    from internbot.providers import available_providers, get_provider_class

    errors: list[str] = []
    seen: dict[str, int] = {}
    for idx, company in enumerate(cfg.companies):
        where = f"companies[{idx}] ({company.name})"
        lowered = company.name.casefold()
        if lowered in seen:
            errors.append(f"{where} : nom en double (déjà utilisé par companies[{seen[lowered]}])")
        seen[lowered] = idx

        try:
            provider_cls = get_provider_class(company.provider)
        except KeyError:
            errors.append(
                f"{where} : provider inconnu '{company.provider}'. "
                f"Disponibles : {', '.join(available_providers())}"
            )
            continue

        opts = company.options
        missing = [f for f in provider_cls.required_fields if opts.get(f) in (None, "")]
        if missing:
            errors.append(
                f"{where} : champ(s) obligatoire(s) manquant(s) pour provider "
                f"'{company.provider}' : {', '.join(missing)}"
            )
        allowed = set(provider_cls.required_fields) | set(provider_cls.optional_fields)
        unknown = sorted(set(opts) - allowed)
        if unknown:
            errors.append(
                f"{where} : champ(s) inconnu(s) pour provider '{company.provider}' : "
                f"{', '.join(unknown)} (autorisés : {', '.join(sorted(allowed)) or 'aucun'})"
            )
        if company.filters is not None:
            try:
                cfg.filters_for(company)
            except ValidationError as exc:
                for err in exc.errors():
                    loc = ".".join(str(p) for p in err["loc"])
                    errors.append(f"{where}.filters.{loc} : {err['msg']}")

    if errors:
        raise ConfigError(f"Configuration invalide ({source}) :\n  - " + "\n  - ".join(errors))


def _format_validation_error(exc: ValidationError, raw: dict[str, Any], source: str) -> str:
    lines = []
    for err in exc.errors():
        loc_parts = list(err["loc"])
        label = _loc_label(loc_parts, raw)
        msg = err["msg"]
        if err["type"] == "missing":
            msg = "champ obligatoire manquant"
        elif err["type"] == "extra_forbidden":
            msg = "champ inconnu (faute de frappe ?)"
        lines.append(f"{label} : {msg}")
    return f"Configuration invalide ({source}) :\n  - " + "\n  - ".join(lines)


def _loc_label(loc: list[Any], raw: dict[str, Any]) -> str:
    parts: list[str] = []
    for i, part in enumerate(loc):
        if isinstance(part, int):
            parts[-1] = f"{parts[-1]}[{part}]"
            if i == 1 and loc[0] == "companies":
                companies = raw.get("companies")
                if isinstance(companies, list) and part < len(companies):
                    entry = companies[part]
                    if isinstance(entry, dict) and entry.get("name"):
                        parts[-1] += f" ({entry['name']})"
        else:
            parts.append(str(part))
    return ".".join(parts) or "racine"
