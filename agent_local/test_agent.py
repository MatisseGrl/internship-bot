import json
import os
import tempfile
import unittest
from pathlib import Path

from agent import (
    classer,
    decider,
    dossier,
    etape_formulaire,
    file,
    importer_simplify,
    initialiser,
    marquer_relu,
    url_canonique,
)
from suivi_candidatures import cle, enregistrer_mail, ouvrir


class AgentTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        ancien_profil = os.environ.get("INTERNBOT_PROFILE")
        self.addCleanup(
            lambda: (
                os.environ.__setitem__("INTERNBOT_PROFILE", ancien_profil)
                if ancien_profil is not None
                else os.environ.pop("INTERNBOT_PROFILE", None)
            )
        )
        profil_test = Path(self.temp.name) / "profil.json"
        profil_test.write_text(
            json.dumps(
                {"faits": {"aero_predict": "Projet ML"}, "cv": {"CV_EU.pdf": {"zone": "Europe"}}}
            ),
            encoding="utf-8",
        )
        os.environ["INTERNBOT_PROFILE"] = str(profil_test)
        self.db = ouvrir(Path(self.temp.name) / "suivi.sqlite")
        self.addCleanup(self.db.close)
        initialiser(self.db)

    def offre(
        self,
        entreprise="Exemple",
        identifiant="42",
        texte="Stage logiciel à Paris.",
        categorie="gardee",
        note=None,
        url="https://example.org/jobs/42",
    ):
        self.db.execute(
            """INSERT INTO offres(cle,entreprise,identifiant,titre,lieu,url,texte,
               categorie_note,note_json,dans_snapshot,vu_le) VALUES(?,?,?,?,?,?,?,?,?,1,?)""",
            (
                cle(entreprise, identifiant),
                entreprise,
                identifiant,
                "Stage IA",
                "Paris",
                url,
                texte,
                categorie,
                json.dumps(note or {}),
                "2026-10-15",
            ),
        )

    def test_simplify_rapproche_l_url_du_bot_et_import_est_idempotent(self):
        self.offre()
        export = Path(self.temp.name) / "simplify.json"
        export.write_text(
            json.dumps(
                [
                    {
                        "company": "Exemple",
                        "title": "Stage IA",
                        "url": "https://example.org/jobs/42?utm_source=simplify",
                        "id": "s-1",
                        "description": "Annonce Simplify",
                    }
                ]
            ),
            encoding="utf-8",
        )
        self.assertEqual(importer_simplify(self.db, export)["rapprochees"], 1)
        self.assertEqual(importer_simplify(self.db, export)["rapprochees"], 1)
        self.assertEqual(self.db.execute("SELECT count(*) FROM offres").fetchone()[0], 1)
        self.assertEqual(self.db.execute("SELECT count(*) FROM sources_offres").fetchone()[0], 1)
        self.assertEqual(
            url_canonique("https://EXAMPLE.org/jobs/42?utm_source=x#top"),
            "https://example.org/jobs/42",
        )

    def test_exclusion_eligibilite_et_historique_qualite(self):
        self.offre("Eligible", "1")
        self.offre(
            "Ineligible",
            "2",
            categorie="ecartee",
            note={"motif": "niveau"},
            url="https://example.org/2",
        )
        self.offre(
            "Qualite", "3", categorie="ecartee", note={"score": 61}, url="https://example.org/3"
        )
        compte = classer(self.db)
        self.assertEqual(compte["inelegible"], 1)
        self.assertEqual(compte["a_qualifier"], 2)
        self.assertEqual(len(file(self.db)), 2)

    def test_export_simplify_sans_url_conserve_historique_sans_postuler(self):
        export = Path(self.temp.name) / "tracker.csv"
        export.write_text(
            "Company name,Position Title,Location,Application Status\n"
            "Autre,Stage Data,Paris,Applied\n",
            encoding="utf-8",
        )
        self.assertEqual(importer_simplify(self.db, export)["ajoutees"], 1)
        self.assertEqual(classer(self.db)["deja_traitees"], 1)
        self.assertEqual(file(self.db), [])
        self.assertEqual(
            self.db.execute("SELECT statut FROM candidatures").fetchone()[0], "envoyee"
        )

    def test_decision_par_offre_cv_et_preuve_de_reception(self):
        self.offre()
        classer(self.db)
        with self.assertRaises(ValueError):
            decider(
                self.db,
                "Exemple",
                "42",
                {
                    "etat": "prete_a_remplir",
                    "raison": "fit",
                    "citation_annonce": "citation inventee",
                    "cv": "CV_EU.pdf",
                    "justification_cv": "Paris",
                    "arguments": [
                        {
                            "citation_annonce": "citation inventee",
                            "fait_cv": "aero_predict",
                            "usage": "IA",
                        }
                    ],
                },
            )
        decider(
            self.db,
            "Exemple",
            "42",
            {
                "etat": "prete_a_remplir",
                "raison": "Stage logiciel pertinent",
                "citation_annonce": "Stage logiciel à Paris.",
                "cv": "CV_EU.pdf",
                "justification_cv": "Poste européen",
                "arguments": [
                    {
                        "citation_annonce": "Stage logiciel à Paris.",
                        "fait_cv": "aero_predict",
                        "usage": "Relier le projet au poste",
                    }
                ],
            },
        )
        dossier_offre = dossier(self.db, "Exemple", "42")
        self.assertEqual(dossier_offre["cv"], "CV_EU.pdf")
        self.assertTrue(
            any("chaque fenêtre de connexion" in x for x in dossier_offre["consignes"])
        )
        self.assertTrue(any("attestations requises" in x for x in dossier_offre["consignes"]))
        etape_formulaire(self.db, "Exemple", "42", "formulaire_en_cours")
        etape_formulaire(self.db, "Exemple", "42", "prete_a_envoyer")
        with self.assertRaises(ValueError):
            etape_formulaire(self.db, "Exemple", "42", "envoi_en_cours")
        marquer_relu(self.db, "Exemple", "42")
        etape_formulaire(self.db, "Exemple", "42", "envoi_en_cours")
        with self.assertRaises(ValueError):
            etape_formulaire(self.db, "Exemple", "42", "envoyee")
        etape_formulaire(self.db, "Exemple", "42", "envoyee", "page de confirmation /42")
        with self.assertRaises(ValueError):
            etape_formulaire(self.db, "Exemple", "42", "envoi_en_cours")
        self.assertEqual(self.db.execute("SELECT count(*) FROM tentatives").fetchone()[0], 1)

    def test_accuse_tardif_nefface_pas_refus(self):
        self.offre()
        self.assertEqual(
            enregistrer_mail(
                self.db,
                boite="a",
                identifiant_message="refus1",
                categorie="refus",
                entreprise="Exemple",
                identifiant_offre="42",
            ),
            "statut_mis_a_jour",
        )
        self.assertEqual(
            enregistrer_mail(
                self.db,
                boite="a",
                identifiant_message="accuse2",
                categorie="confirmation",
                entreprise="Exemple",
                identifiant_offre="42",
            ),
            "mail_enregistre_sans_regression",
        )
        self.assertEqual(
            self.db.execute("SELECT statut FROM candidatures").fetchone()[0], "refusee"
        )

    def test_demande_de_repostuler_remonte_en_priorite(self):
        self.offre("Microsoft", "200061386", texte="Stage logiciel à Dublin.")
        self.db.execute(
            "INSERT INTO candidatures(cle_offre,statut,modifie_le) VALUES(?,?,?)",
            (cle("Microsoft", "200061386"), "action_requise", "2026-10-15"),
        )
        self.assertEqual(classer(self.db)["action_requise"], 1)
        self.assertEqual(file(self.db)[0]["identifiant"], "200061386")


if __name__ == "__main__":
    unittest.main()
