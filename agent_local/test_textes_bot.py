import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from suivi_candidatures import cle
from textes_bot import importer

LONG = "Build and ship ML systems. " * 20


class TextesBotTest(unittest.TestCase):
    def test_complete_sans_ecraser(self):
        db = sqlite3.connect(":memory:")
        db.execute("CREATE TABLE offres(cle TEXT PRIMARY KEY, texte TEXT)")
        db.executemany(
            "INSERT INTO offres VALUES(?,?)",
            [(cle("Acme", "1"), None), (cle("Acme", "2"), "texte de la note " * 30)],
        )
        lignes = [
            {"company": "Acme", "job_id": "1", "texte": LONG},
            {"company": "Acme", "job_id": 2, "texte": LONG},
            {"company": "Acme", "job_id": "3", "texte": LONG},
            {"company": "Acme", "job_id": "4", "erreur": "HTTP 404"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            export = Path(tmp) / "textes.jsonl"
            export.write_text("\n".join(json.dumps(x) for x in lignes), encoding="utf-8")
            compte = importer(db, export)
        self.assertEqual(
            compte, {"lues": 4, "ajoutees": 1, "deja_texte": 1, "inconnues": 1, "erreurs": 1}
        )
        textes = dict(db.execute("SELECT cle,texte FROM offres"))
        self.assertEqual(textes[cle("Acme", "1")], LONG)
        self.assertTrue(textes[cle("Acme", "2")].startswith("texte de la note"))


if __name__ == "__main__":
    unittest.main()
