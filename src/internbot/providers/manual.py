"""Entreprise suivie À LA MAIN : aucune requête automatique.

Pour les sites sans API ni endpoint JSON stable, ou protégés (anti-bot, robots.txt qui interdit
la collecte, authentification). On ne tente aucun contournement : l'entrée sert de mémo
(raison + lien pour créer l'alerte e-mail native du site) et apparaît dans `--status`.

    - name: Google
      provider: manual
      careers_url: https://www.google.com/about/careers/applications/jobs/results?q=intern
      reason: "robots.txt interdit /about/careers/applications/jobs/results"
      alert: "Créer une alerte : bouton « Get job alerts » sur la page de résultats"
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from internbot.errors import ProviderError
from internbot.models import Job
from internbot.providers.base import Provider, register

if TYPE_CHECKING:
    from internbot.config import CompanyConfig


@register
class ManualProvider(Provider):
    name = "manual"
    automated = False
    required_fields = ("careers_url", "reason")
    optional_fields = ("alert",)

    def fetch_jobs(self, company: CompanyConfig) -> list[Job]:
        raise ProviderError(
            f"{company.name} est suivie à la main ({company.opt('reason')}) : "
            f"{company.opt('careers_url')}"
        )
