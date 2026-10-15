import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from import_swelist import importer


class ImportSWElistTests(unittest.TestCase):
    def test_source_stays_separate_and_import_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            inventory = Path(folder) / "swelist.csv"
            with inventory.open("w", encoding="utf-8", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=[
                    "date_mail", "id_mail", "entreprise", "intitule",
                    "lien_simplify", "premier_filtre", "raison",
                ])
                writer.writeheader()
                writer.writerow({"date_mail": "2026-10-15", "id_mail": "mail-1",
                    "entreprise": "Example", "intitule": "Software Engineer Intern",
                    "lien_simplify": "https://simplify.jobs/p/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "premier_filtre": "retenir_titre", "raison": "titre compatible"})
                writer.writerow({"date_mail": "2026-10-15", "id_mail": "mail-1",
                    "entreprise": "Different", "intitule": "Data Intern",
                    "lien_simplify": "https://simplify.jobs/p/bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                    "premier_filtre": "a_revoir", "raison": "ambigu"})
            db = sqlite3.connect(":memory:")
            db.execute("CREATE TABLE offres(cle TEXT, entreprise TEXT, titre TEXT, url TEXT)")
            db.execute("INSERT INTO offres VALUES('bot-1','Example','Software Engineer Intern','https://example.com/job/1')")
            before = list(db.execute("SELECT * FROM offres"))
            first = importer(db, inventory)
            self.assertEqual(first["ajoutees"], 2)
            self.assertEqual(first["titre_entreprise_unique"], 1)
            self.assertEqual(first["aucun"], 1)
            db.execute("UPDATE swelist_annonces SET label_humain=1 WHERE bot_cle_candidate='bot-1'")
            second = importer(db, inventory)
            self.assertEqual(second["deja_presentes"], 2)
            self.assertEqual(list(db.execute("SELECT * FROM offres")), before)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM swelist_annonces").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT label_humain FROM swelist_annonces WHERE bot_cle_candidate='bot-1'").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
