import unittest

from eligibilite import verifier


def motifs(titre="Software Engineer Intern", texte="", actif=None):
    return {m for m, _ in verifier(titre, texte, actif)}


class EligibiliteTest(unittest.TestCase):
    def test_exclusions_explicites(self):
        self.assertIn("nationalite", motifs(texte="You must be a U.S. citizen to apply."))
        self.assertIn("phd", motifs(texte="Currently enrolled in a PhD program in CS."))
        self.assertIn("fin_etudes", motifs(texte="Vous recherchez votre stage de fin d'études."))
        self.assertIn(
            "diplome_trop_tot", motifs(texte="Expected graduation between Dec 2026 and June 2027.")
        )
        self.assertIn("recherche", motifs(titre="Research Intern - Data Systems"))
        self.assertIn("fermee", motifs(actif=False))

    def test_mentions_qui_n_excluent_pas_matisse(self):
        textes = [
            "Students expected to graduate in December 2027 or Spring 2028.",
            "Graduating December 2027 or later.",
            "Candidates must not graduate prior to December 2027.",
            "Active US security clearance, or eligibility and willingness to obtain one.",
            "Currently enrolled in a PhD or MS program in Computer Science.",
            "Final year student preferred but not required.",
        ]
        for texte in textes:
            with self.subTest(texte=texte):
                self.assertEqual(motifs(texte=texte), set())
        self.assertEqual(motifs(titre="Research Engineer Intern"), set())

    def test_preuve_est_la_phrase(self):
        (motif, preuve), *_ = verifier(
            "Intern", "Great team. This role requires a U.S. Person. Apply!"
        )
        self.assertEqual(motif, "nationalite")
        self.assertEqual(preuve, "This role requires a U.S. Person.")


if __name__ == "__main__":
    unittest.main()
