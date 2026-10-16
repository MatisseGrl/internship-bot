"""Connexion Google aux portails de candidature avec Playwright.

Ce module ne saisit aucun mot de passe et ne soumet aucune candidature.
Il attend une page de candidature déjà ouverte dans un navigateur contrôlé
par Playwright, avec la session Google du candidat déjà disponible.
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlsplit


class ConnexionInattendue(RuntimeError):
    """L'écran affiché ne correspond pas au parcours autorisé."""


def _hote(url: str) -> str | None:
    morceaux = urlsplit(url)
    return morceaux.hostname if morceaux.scheme == "https" else None


def connecter_google(
    page,
    email: str,
    *,
    site_hote: str,
    destination_google: str,
    libelle_google: str = "Sign in using Google",
    timeout_ms: int = 15_000,
) -> str:
    """Applique le parcours obligatoire à chaque fenêtre de connexion connue.

    Le domaine du portail et celui annoncé par Google sont fournis pour chaque
    site. En cas de variante inconnue, la fonction s'arrête avant Continue.
    L'appelant doit ensuite vérifier que la connexion a réellement abouti.
    """
    if not site_hote or not destination_google:
        raise ValueError("Domaines du portail et de la destination Google requis")
    if _hote(page.url) != site_hote:
        raise ConnexionInattendue("La page de départ ne correspond pas au portail attendu")
    if not email or "@" not in email:
        raise ValueError("Adresse Google du candidat requise")

    # 1. Ouvre la fenêtre Google depuis la modale de connexion du portail.
    with page.expect_popup(timeout=timeout_ms) as nouvelle_fenetre:
        page.get_by_role("button", name=libelle_google, exact=True).click(timeout=timeout_ms)
    google = nouvelle_fenetre.value
    google.wait_for_url(re.compile(r"^https://accounts\.google\.com/"), timeout=timeout_ms)
    if _hote(google.url) != "accounts.google.com":
        raise ConnexionInattendue("La fenêtre ouverte n'est pas sur accounts.google.com")

    # 2. Choisit l'adresse exacte ; aucun choix par position dans la liste.
    compte = google.get_by_text(email, exact=True).first
    compte.wait_for(state="visible", timeout=timeout_ms)
    selection = google.get_by_role("heading", name="Choose an account")
    if selection.is_visible():
        compte.click(timeout=timeout_ms)

    # 3. L'écran de consentement doit encore afficher la bonne adresse et
    #    nommer le prestataire attendu avant que Continue soit actionné.
    continuer = google.get_by_role("button", name="Continue", exact=True)
    continuer.wait_for(state="visible", timeout=timeout_ms)
    if _hote(google.url) != "accounts.google.com":
        raise ConnexionInattendue("La fenêtre Google a changé de domaine")
    texte = google.locator("body").inner_text(timeout=timeout_ms)
    if email not in texte:
        raise ConnexionInattendue("Le compte Google affiché ne correspond pas")
    destination = re.escape(destination_google)
    if not re.search(
        rf"(?:signing back in|signing in|sign in|continue) to\s+{destination}(?![\w.-])",
        texte,
        re.I,
    ):
        raise ConnexionInattendue("La destination Google ne correspond pas au portail attendu")
    continuer.click(timeout=timeout_ms)
    return "continue_clique"


def connecter_google_microsoft(page, email: str, timeout_ms: int = 15_000) -> str:
    """Parcours Microsoft Careers avec destination Google Eightfold vérifiée."""
    return connecter_google(
        page,
        email,
        site_hote="microsoft.eightfold.ai",
        destination_google="eightfold.ai",
        timeout_ms=timeout_ms,
    )


def main() -> None:
    """Utilise un Chrome déjà exposé à Playwright via son port CDP local."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SystemExit("Installer Playwright : pip install -e '.[playwright]'") from exc

    email = os.environ.get("INTERNBOT_GOOGLE_EMAIL", "").strip()
    if not email:
        raise SystemExit("Définir INTERNBOT_GOOGLE_EMAIL pour le compte candidat")
    cdp = os.environ.get("INTERNBOT_CDP_URL", "http://127.0.0.1:9222")
    with sync_playwright() as playwright:
        navigateur = playwright.chromium.connect_over_cdp(cdp)
        pages = [
            page
            for contexte in navigateur.contexts
            for page in contexte.pages
            if _hote(page.url) == "microsoft.eightfold.ai"
        ]
        if len(pages) != 1:
            raise SystemExit(
                f"Une seule page Microsoft Careers est requise ; {len(pages)} trouvée(s)"
            )
        print(connecter_google_microsoft(pages[0], email))


if __name__ == "__main__":
    main()
