"""Interface commune des notifiers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from internbot.models import Job


class Notifier(ABC):
    @abstractmethod
    def notify(self, jobs: Sequence[Job]) -> list[Job]:
        """Envoie les offres. Retourne UNIQUEMENT celles dont l'envoi a réussi."""

    @abstractmethod
    def send_text(self, text: str) -> bool:
        """Envoie un message informatif en texte brut (alerte, récapitulatif, test)."""

    @abstractmethod
    def send_listing(self, jobs: Sequence[Job], *, subtitle: str = "") -> bool:
        """Envoie la liste complète des offres ouvertes. True si tout est parti."""
