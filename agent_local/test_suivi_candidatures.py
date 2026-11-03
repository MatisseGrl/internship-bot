import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from suivi_candidatures import bilan, enregistrer_mail, ouvrir, synchroniser


class SuiviCandidaturesTest(unittest.TestCase):
    def test_import_et_mail_sont_idempotents(self):
        with tempfile.TemporaryDirectory() as dossier:
            archive = Path(dossier) / "offres.jsonl"
            archive.write_text(
                '{"company":"Exemple","job_id":"42","title":"Stage IA",'
                '"url":"https://example.org/42","texte":"Annonce complète"}\n',
                encoding="utf-8",
            )
            notes = {"offres": {"Exemple": {"42": {"score": 80}}}, "ecartees": {}}
            snapshot = {
                "version": 1,
                "companies": {
                    "Exemple": {
                        "jobs": [
                            {"job_id": "42", "title": "Stage IA", "url": "https://example.org/42"}
                        ]
                    }
                },
            }
            with closing(ouvrir(Path(dossier) / "suivi.sqlite")) as db:
                synchroniser(db, notes, [archive], snapshot)
                self.assertEqual(
                    enregistrer_mail(
                        db,
                        boite="boite1",
                        identifiant_message="m1",
                        categorie="confirmation",
                        entreprise="Exemple",
                        identifiant_offre="42",
                    ),
                    "statut_mis_a_jour",
                )
                self.assertEqual(
                    enregistrer_mail(
                        db,
                        boite="boite1",
                        identifiant_message="m1",
                        categorie="confirmation",
                        entreprise="Exemple",
                        identifiant_offre="42",
                    ),
                    "deja_enregistre",
                )
                synchroniser(db, notes, [archive], snapshot)
                self.assertEqual(bilan(db)["offres"], 1)
                self.assertEqual(bilan(db)["mails"], 1)
                self.assertEqual(
                    db.execute("SELECT statut FROM candidatures").fetchone()[0], "envoyee"
                )

    def test_mail_ambigu_ne_change_pas_de_candidature(self):
        with (
            tempfile.TemporaryDirectory() as dossier,
            closing(ouvrir(Path(dossier) / "suivi.sqlite")) as db,
        ):
            self.assertEqual(
                enregistrer_mail(
                    db,
                    boite="boite1",
                    identifiant_message="m2",
                    categorie="refus",
                    entreprise="Inconnue",
                    identifiant_offre="99",
                ),
                "a_verifier",
            )
            self.assertEqual(bilan(db)["candidatures"], 0)
            self.assertEqual(bilan(db)["mails_a_verifier"], 1)

    def test_action_liee_reste_a_verifier(self):
        with (
            tempfile.TemporaryDirectory() as dossier,
            closing(ouvrir(Path(dossier) / "suivi.sqlite")) as db,
        ):
            db.execute(
                "INSERT INTO offres(cle,entreprise,identifiant,vu_le) VALUES(?,?,?,?)",
                ("Microsoft\x1f42", "Microsoft", "42", "2026-10-15"),
            )
            self.assertEqual(
                enregistrer_mail(
                    db,
                    boite="boite1",
                    identifiant_message="m3",
                    categorie="action",
                    entreprise="Microsoft",
                    identifiant_offre="42",
                ),
                "a_verifier",
            )
            self.assertEqual(bilan(db)["mails_a_verifier"], 1)
            self.assertEqual(bilan(db)["candidatures"], 0)


if __name__ == "__main__":
    unittest.main()
