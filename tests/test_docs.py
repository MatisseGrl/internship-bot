"""La doc des sites bloqués (docs/SITES_BLOQUES.md) reste le document unique et complet."""

from __future__ import annotations

from pathlib import Path

from internbot.config import load_config

RACINE = Path(__file__).resolve().parents[1]


def test_toute_entreprise_manuelle_est_dans_sites_bloques() -> None:
    doc = (RACINE / "docs" / "SITES_BLOQUES.md").read_text(encoding="utf-8")
    manuelles = [
        c.name for c in load_config(RACINE / "config.yaml").companies if c.provider == "manual"
    ]
    absentes = [nom for nom in manuelles if f"[{nom}](" not in doc]
    assert manuelles and not absentes, f"à ajouter dans docs/SITES_BLOQUES.md : {absentes}"
