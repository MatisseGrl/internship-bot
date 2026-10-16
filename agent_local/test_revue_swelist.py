import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from revue_swelist import import_labels


class ReviewTests(unittest.TestCase):
    def test_conflicting_feedback_does_not_overwrite_a_human_label(self):
        with tempfile.TemporaryDirectory() as folder:
            db = sqlite3.connect(":memory:")
            db.execute(
                "CREATE TABLE swelist_annonces(simplify_id TEXT PRIMARY KEY,label_humain INTEGER)"
            )
            db.execute("INSERT INTO swelist_annonces VALUES('known',1)")
            source = Path(folder) / "review.csv"
            with source.open("w", encoding="utf-8", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=["simplify_id", "label_humain"])
                writer.writeheader()
                writer.writerow({"simplify_id": "known", "label_humain": "0"})
            with self.assertRaisesRegex(ValueError, "déjà différente"):
                import_labels(db, source)
            self.assertEqual(
                db.execute("SELECT label_humain FROM swelist_annonces").fetchone()[0], 1
            )


if __name__ == "__main__":
    unittest.main()
