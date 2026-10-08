from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from internbot.config import load_config, parse_config
from internbot.errors import ConfigError

ROOT = Path(__file__).resolve().parents[1]


def base(**companies: Any) -> dict[str, Any]:
    return {"companies": [{"name": "Acme", "provider": "greenhouse", "board": "acme"}]}


def test_example_config_is_valid() -> None:
    cfg = load_config(ROOT / "config.example.yaml")
    names = [c.name for c in cfg.companies]
    assert "Salesforce" in names
    sf = next(c for c in cfg.companies if c.name == "Salesforce")
    assert sf.opt("tenant") == "salesforce" and sf.opt("wd") == "wd12"


def test_defaults_applied() -> None:
    cfg = parse_config(base())
    assert cfg.notifier.type == "telegram"
    assert "intern" in cfg.filters.title_include
    assert cfg.http.min_delay_s >= 1.0


def test_missing_file() -> None:
    with pytest.raises(ConfigError, match="introuvable"):
        load_config("nope.yaml")


def test_invalid_yaml(tmp_path: Path) -> None:
    p = tmp_path / "c.yaml"
    p.write_text("companies: [", encoding="utf-8")
    with pytest.raises(ConfigError, match="YAML invalide"):
        load_config(p)


def test_unknown_provider_lists_available() -> None:
    with pytest.raises(ConfigError, match=r"provider inconnu 'taleo'.*workday"):
        parse_config({"companies": [{"name": "X", "provider": "taleo"}]})


def test_missing_provider_field() -> None:
    raw = {"companies": [{"name": "Salesforce", "provider": "workday", "tenant": "salesforce"}]}
    with pytest.raises(ConfigError, match=r"Salesforce.*manquant.*wd, site"):
        parse_config(raw)


def test_missing_name() -> None:
    with pytest.raises(ConfigError, match=r"companies\[0\]\.name : champ obligatoire manquant"):
        parse_config({"companies": [{"provider": "greenhouse", "board": "x"}]})


def test_typo_in_provider_field_detected() -> None:
    raw = {
        "companies": [
            {
                "name": "S",
                "provider": "workday",
                "tenant": "s",
                "wd": "wd1",
                "site": "x",
                "serach_text": "intern",
            }
        ]
    }
    with pytest.raises(ConfigError, match=r"champ\(s\) inconnu\(s\).*serach_text"):
        parse_config(raw)


def test_typo_in_top_level_section() -> None:
    raw = base()
    raw["filtres"] = {}
    with pytest.raises(ConfigError, match="filtres : champ inconnu"):
        parse_config(raw)


def test_duplicate_company_names() -> None:
    raw = {
        "companies": [
            {"name": "Acme", "provider": "greenhouse", "board": "a"},
            {"name": "acme", "provider": "lever", "company": "a"},
        ]
    }
    with pytest.raises(ConfigError, match="double"):
        parse_config(raw)


def test_empty_companies() -> None:
    with pytest.raises(ConfigError):
        parse_config({"companies": []})


def test_min_delay_politeness_enforced() -> None:
    raw = base()
    raw["http"] = {"min_delay_s": 0.2}
    with pytest.raises(ConfigError, match="min_delay_s"):
        parse_config(raw)


def test_company_filter_override_merges() -> None:
    raw = {
        "filters": {"locations_include": [], "keywords_any": ["software"]},
        "companies": [
            {
                "name": "A",
                "provider": "greenhouse",
                "board": "a",
                "filters": {"locations_include": ["France"]},
            }
        ],
    }
    cfg = parse_config(raw)
    merged = cfg.filters_for(cfg.companies[0])
    assert merged.locations_include == ["France"]
    assert merged.keywords_any == ["software"]


def test_company_filter_override_validated() -> None:
    raw = {
        "companies": [
            {"name": "A", "provider": "greenhouse", "board": "a", "filters": {"year_mode": "x"}}
        ]
    }
    with pytest.raises(ConfigError, match=r"A\)\.filters\.year_mode"):
        parse_config(raw)
