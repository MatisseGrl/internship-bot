import tempfile
import unittest
from pathlib import Path

from agent import initialiser
from import_tracker import importer
from suivi_candidatures import cle, ouvrir


def ligne(numero, entreprise, poste, statut="Postulé", **autres):
    return {
        "feuille": "US",
        "numero": numero,
        "entreprise": entreprise,
        "poste": poste,
        "statut": statut,
        "date_candidature": "2026-10-05",
        **autres,
    }


class TrackerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = ouvrir(Path(self.temp.name) / "suivi.sqlite")
        self.addCleanup(self.db.close)
        initialiser(self.db)
        for entreprise, identifiant, titre in [
            ("Cisco", "2026798", "Software Engineer Data & AI II (Intern) – United States"),
            (
                "Mistral AI",
                "m1",
                "Applied AI, Forward Deployed Machine Learning Engineer - (Internship)",
            ),
            ("Palantir", "p1", "Software Engineer, Internship"),
            ("Palantir", "p2", "Software Engineer, Internship"),
        ]:
            self.db.execute(
                "INSERT INTO offres(cle,entreprise,identifiant,titre,vu_le) VALUES(?,?,?,?,?)",
                (cle(entreprise, identifiant), entreprise, identifiant, titre, "2026-10-15"),
            )
        self.db.commit()

    def statut(self, offre_cle):
        row = self.db.execute(
            "SELECT statut FROM candidatures WHERE cle_offre=?", (offre_cle,)
        ).fetchone()
        return row[0] if row else None

    def test_rapprochements_et_offres_creees(self):
        lignes = [
            ligne(1, "Cisco", "Software Engineer Data & AI II (Intern)", notes="ID 2026798"),
            ligne(
                2,
                "Mistral AI",
                "Applied AI, Forward Deployed Machine Learning Engineer (Internship)",
                statut="À postuler",
            ),
            ligne(3, "Palantir", "Software Engineer, Internship"),  # deux offres : ambigu
            ligne(
                4,
                "Google",
                "SWE Intern",
                lien="https://www.google.com/about/careers/applications/dashboard?hl=en_US",
            ),
            ligne(
                5,
                "Google",
                "Student Researcher",
                lien="https://www.google.com/about/careers/applications/dashboard?hl=en_US",
            ),
        ]
        compte = importer(self.db, lignes, {"Réponses Palantir": "texte"})
        modes = dict(
            self.db.execute("SELECT numero, rapprochement FROM suivi_manuel ORDER BY numero")
        )
        self.assertEqual(
            modes,
            {
                1: "identifiant",
                2: "titre_unique",
                3: "nouvelle_offre",
                4: "nouvelle_offre",
                5: "nouvelle_offre",
            },
        )
        self.assertEqual(self.statut(cle("Cisco", "2026798")), "envoyee")
        self.assertIsNone(self.statut(cle("Mistral AI", "m1")))  # « À postuler »
        google = self.db.execute("SELECT count(*) FROM offres WHERE entreprise='Google'").fetchone()
        self.assertEqual(google[0], 2)  # le lien de tableau de bord ne fusionne pas
        self.assertEqual(compte["candidatures"], 4)
        self.assertEqual(
            self.db.execute("SELECT texte FROM reponses_candidature").fetchone()[0], "texte"
        )

    def test_meme_titre_dans_deux_onglets_reste_deux_candidatures(self):
        londres = {**ligne(4, "Palantir", "FDSE"), "feuille": "Europe", "lieu": "Londres"}
        new_york = {**ligne(8, "Palantir", "FDSE"), "lieu": "New York"}
        importer(self.db, [londres, new_york], {})
        cles = {r[0] for r in self.db.execute("SELECT cle_offre FROM suivi_manuel")}
        self.assertEqual(len(cles), 2)
        self.assertEqual(self.db.execute("SELECT count(*) FROM candidatures").fetchone()[0], 2)

    def test_reimport_idempotent_et_sans_retrogradation(self):
        lignes = [ligne(1, "Cisco", "SWE", notes="ID 2026798"), ligne(2, "Acme", "ML Intern")]
        importer(self.db, lignes, {})
        self.db.execute(
            "UPDATE candidatures SET statut='refusee' WHERE cle_offre=?", (cle("Cisco", "2026798"),)
        )
        self.db.commit()
        compte = importer(self.db, lignes, {})
        self.assertEqual(compte["gardees"], 1)
        self.assertEqual(self.statut(cle("Cisco", "2026798")), "refusee")
        self.assertEqual(self.db.execute("SELECT count(*) FROM offres").fetchone()[0], 5)
        self.assertEqual(self.db.execute("SELECT count(*) FROM suivi_manuel").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
