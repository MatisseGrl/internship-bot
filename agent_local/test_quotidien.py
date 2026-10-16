import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

try:
    from quotidien import textes_manquants
except ImportError:  # dépendances optionnelles : pip install -e ".[ml]"
    textes_manquants = None


class QuotidienTest(unittest.TestCase):
    def test_selection_des_textes_manquants(self):
        if textes_manquants is None:
            self.skipTest("dépendances ML absentes")
        db = sqlite3.connect(":memory:")
        db.execute(
            """CREATE TABLE offres(cle TEXT, entreprise TEXT, identifiant TEXT, texte TEXT,
               note_json TEXT, dans_snapshot INTEGER)"""
        )
        db.executemany(
            "INSERT INTO offres VALUES(?,?,?,?,?,?)",
            [
                ("a", "Acme", "1", None, None, 1),  # à lire
                ("b", "Acme", "2", "x" * 500, None, 1),  # texte déjà là
                ("c", "Acme", "3", None, '{"notes": [4]}', 1),  # déjà notée
                ("d", "Acme", "4", "court", None, 0),  # plus dans l'instantané
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            selection = Path(tmp) / "sel.jsonl"
            self.assertEqual(textes_manquants(db, selection), 1)
            lignes = [json.loads(x) for x in selection.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(lignes, [{"company": "Acme", "job_id": "1"}])


if __name__ == "__main__":
    unittest.main()
