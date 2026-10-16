"""Tests du parcours de connexion sans ouvrir de compte réel."""

import unittest
from contextlib import contextmanager

from google_signin import ConnexionInattendue, connecter_google_microsoft


class Element:
    def __init__(self, journal, nom, visible=True):
        self.journal = journal
        self.nom = nom
        self.visible = visible
        self.first = self

    def click(self, **_):
        self.journal.append(self.nom)

    def wait_for(self, **_):
        if not self.visible:
            raise AssertionError(f"{self.nom} ne devrait pas être attendu")

    def is_visible(self):
        return self.visible


class FausseFenetreGoogle:
    url = "https://accounts.google.com/v3/signin/accountchooser"

    def __init__(self, journal, corps):
        self.journal = journal
        self.corps = corps

    def wait_for_url(self, *_args, **_kwargs):
        pass

    def get_by_text(self, texte, **_):
        return Element(self.journal, f"compte:{texte}")

    def get_by_role(self, role, name, **_):
        if role == "heading" and name == "Choose an account":
            return Element(self.journal, "choix", visible=True)
        if role == "button" and name == "Continue":
            return Element(self.journal, "continuer")
        raise AssertionError((role, name))

    def locator(self, selecteur):
        assert selecteur == "body"
        return self

    def inner_text(self, **_):
        return self.corps


class FaussePageMicrosoft:
    url = "https://microsoft.eightfold.ai/careers/applications"

    def __init__(self, google, journal):
        self.google = google
        self.journal = journal

    @contextmanager
    def expect_popup(self, **_):
        resultat = type("Popup", (), {"value": self.google})()
        yield resultat

    def get_by_role(self, role, name, **_):
        assert (role, name) == ("button", "Sign in using Google")
        return Element(self.journal, "google")


class ConnexionGoogleTest(unittest.TestCase):
    def test_trois_clics_dans_l_ordre(self):
        journal = []
        google = FausseFenetreGoogle(
            journal, "You're signing back in to eightfold.ai candidat@example.com"
        )
        page = FaussePageMicrosoft(google, journal)
        self.assertEqual(connecter_google_microsoft(page, "candidat@example.com"), "continue_clique")
        self.assertEqual(journal, ["google", "compte:candidat@example.com", "continuer"])

    def test_mauvais_compte_arrete_avant_continue(self):
        journal = []
        google = FausseFenetreGoogle(journal, "You're signing back in to eightfold.ai autre@example.com")
        page = FaussePageMicrosoft(google, journal)
        with self.assertRaisesRegex(ConnexionInattendue, "compte Google"):
            connecter_google_microsoft(page, "candidat@example.com")
        self.assertNotIn("continuer", journal)

    def test_mauvaise_destination_arrete_avant_continue(self):
        journal = []
        google = FausseFenetreGoogle(journal, "Continue to autre.app candidat@example.com")
        page = FaussePageMicrosoft(google, journal)
        with self.assertRaisesRegex(ConnexionInattendue, "destination"):
            connecter_google_microsoft(page, "candidat@example.com")
        self.assertNotIn("continuer", journal)

    def test_mauvaise_page_de_depart_ne_clique_pas(self):
        journal = []
        google = FausseFenetreGoogle(journal, "")
        page = FaussePageMicrosoft(google, journal)
        page.url = "https://exemple.com"
        with self.assertRaisesRegex(ConnexionInattendue, "page de départ"):
            connecter_google_microsoft(page, "candidat@example.com")
        self.assertEqual(journal, [])


if __name__ == "__main__":
    unittest.main()
