import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
    from test_tri_ml import fake_embed
    from tri_ml import TitleModel
    from tri_texte import BodyEmbedder, TextModel, classer, morceaux, nettoyer, train
except ImportError:  # dépendances optionnelles : pip install -e ".[ml]"
    np = None

GOOD = "You will train machine learning models, ship Python services and deploy LLM agents. "
BAD = "You will design mechanical parts, run hardware tests and support manufacturing lines. "


def registry(path: Path) -> None:
    db = sqlite3.connect(path)
    db.executescript(
        """CREATE TABLE offres(cle TEXT PRIMARY KEY,entreprise TEXT,titre TEXT,lieu TEXT,url TEXT,
               texte TEXT,note_json TEXT,dans_snapshot INTEGER);
           CREATE TABLE candidatures(cle_offre TEXT PRIMARY KEY,statut TEXT);
           CREATE TABLE swelist_annonces(simplify_id TEXT PRIMARY KEY,entreprise TEXT,
               intitule TEXT,lien_simplify TEXT,score_fit REAL);
           CREATE TABLE swelist_descriptions(simplify_id TEXT PRIMARY KEY,
               description_texte TEXT,actif INTEGER,lieux TEXT);"""
    )
    rows = []
    for c in range(30):
        for i in range(3):
            rows.append(
                (
                    f"g{c}{i}",
                    f"Co{c}",
                    f"ML Engineer Intern {c}{i}",
                    GOOD * 6,
                    {"notes": [5, 3, 3, 3], "score": 80},
                )
            )
            rows.append(
                (
                    f"b{c}{i}",
                    f"Co{c}",
                    f"Mechanical Intern {c}{i}",
                    BAD * 6,
                    {"notes": [1, 3, 3, 3], "score": 40},
                )
            )
    db.executemany(
        "INSERT INTO offres VALUES(?,?,?,NULL,NULL,?,?,0)",
        [(k, co, t, "Intitulé : x\n" + tx, json.dumps(n)) for k, co, t, tx, n in rows],
    )
    db.executemany(
        "INSERT INTO offres VALUES(?,?,?,?,?,?,NULL,1)",
        [
            ("new1", "Neo", "AI Intern", "Paris", "https://neo/1", GOOD * 6),
            ("new2", "Neo", "Hardware Intern", "Paris", "https://neo/2", BAD * 6),
            ("new3", "Neo", "Data Intern", "Paris", "https://neo/3", None),
        ],
    )
    db.execute("INSERT INTO candidatures VALUES('new1','envoyee')")
    db.executemany(
        "INSERT INTO swelist_annonces VALUES(?,?,?,?,?)",
        [
            ("s1", "Sw", "Software Engineer Intern", "https://simplify.jobs/p/s1", 0.9),
            ("s2", "Sw", "Software Engineer Intern II", "https://simplify.jobs/p/s2", 0.9),
        ],
    )
    db.executemany(
        "INSERT INTO swelist_descriptions VALUES(?,?,?,?)",
        [
            ("s1", GOOD * 6 + " You must be a U.S. citizen.", 1, '["Austin"]'),
            ("s2", GOOD * 6, 0, '["Austin"]'),
        ],
    )
    db.commit()
    db.close()


class TexteTest(unittest.TestCase):
    def setUp(self):
        if np is None:
            self.skipTest("dépendances ML absentes")

    def test_nettoyer_et_morceaux(self):
        self.assertEqual(nettoyer("Intitulé : SWE\nLieu : Paris\nBuild things."), "Build things.")
        self.assertEqual(len(morceaux("x" * 10_000)), 6)

    def test_cache_embeddings_reutilise(self):
        calls = []

        def embed(texts):
            calls.append(len(texts))
            return fake_embed(texts)

        with tempfile.TemporaryDirectory() as tmp:
            premier = BodyEmbedder(embed, Path(tmp) / "c.sqlite")
            first = premier(["alpha " * 300, "beta"])
            premier.close()
            again = BodyEmbedder(embed, Path(tmp) / "c.sqlite")
            second = again(["alpha " * 300, "beta"])
            again.close()
        self.assertEqual(len(calls), 1)
        self.assertTrue(np.allclose(first, second))

    def test_entrainer_puis_classer(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path, model, titre = (
                Path(tmp) / "r.sqlite",
                Path(tmp) / "t.json",
                Path(tmp) / "v3.json",
            )
            registry(db_path)
            report = train(db_path, model, Path(tmp) / "rapport.json", fake_embed)
            self.assertGreater(report["fit"]["hors_pli_toutes_donnees"]["auc"], 0.9)
            artifact = json.loads(model.read_text(encoding="utf-8"))
            reloaded = TextModel.from_artifact(artifact["cibles"]["fit"])
            self.assertEqual(reloaded.vocabulary, artifact["cibles"]["fit"]["vocabulaire"])
            title = TitleModel().fit(["AI Intern", "Hardware Intern"] * 3, [1, 0] * 3, fake_embed)
            titre.write_text(
                json.dumps(
                    {"seuil_basse_priorite": 0.1, "seuil_prioriser": 0.8, **title.to_artifact()}
                ),
                encoding="utf-8",
            )
            sortie = Path(tmp) / "classement.csv"
            result = classer(db_path, model, titre, sortie, fake_embed)
            self.assertEqual(result["total"], 5)
            self.assertEqual(result["avec_texte"], 4)
            with sortie.open(encoding="utf-8-sig") as fh:
                lignes = {r["titre"]: r for r in csv.DictReader(fh, delimiter=";")}
            self.assertEqual(lignes["Data Intern"]["base"], "titre")
            self.assertEqual(lignes["AI Intern"]["deja_candidature"], "1")
            self.assertIn("nationalite", lignes["Software Engineer Intern"]["motifs"])
            self.assertIn("fermee", lignes["Software Engineer Intern II"]["motifs"])
            self.assertEqual({r["doublon_du_rang"] for r in lignes.values()}, {""})
            # Une offre qui disparaît reste dans la table, marquée absente et sans rang.
            db = sqlite3.connect(db_path)
            with db:
                db.execute("UPDATE offres SET dans_snapshot=0 WHERE cle='new2'")
            db.close()
            classer(db_path, model, titre, sortie, fake_embed)
            db = sqlite3.connect(db_path)
            present, rang = db.execute(
                "SELECT present, rang FROM classement WHERE identifiant='new2'"
            ).fetchone()
            total = db.execute("SELECT count(*) FROM classement").fetchone()[0]
            db.close()
            self.assertEqual((present, rang, total), (0, None, 5))
            self.assertGreater(
                float(lignes["AI Intern"]["score_fit"]),
                float(lignes["Hardware Intern"]["score_fit"]),
            )


if __name__ == "__main__":
    unittest.main()
