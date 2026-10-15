import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    from tri_ml import (
        CHAR_NGRAMS,
        TitleModel,
        load_examples,
        score_only,
        split_company,
        train,
    )
except ImportError:  # dépendances optionnelles : pip install -e ".[ml]"
    np = None


def fake_embed(titles):
    """Sac de mots haché : déterministe et sans téléchargement de modèle."""
    vectors = np.zeros((len(titles), 32))
    for row, title in enumerate(titles):
        for word in title.lower().split():
            vectors[row, int(hashlib.sha256(word.encode()).hexdigest(), 16) % 32] += 1
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.where(norms == 0, 1, norms)


def query(path: Path, sql: str) -> list:
    db = sqlite3.connect(path)
    try:
        return db.execute(sql).fetchall()
    finally:
        db.close()  # Windows refuse de supprimer un fichier encore ouvert


GOOD = ["Software Engineer", "Machine Learning", "Data Scientist", "AI Engineer", "Backend"]
BAD = ["Mechanical Engineer", "Hardware Test", "Accountant", "Marketing", "Sales"]


def registry(path: Path, companies: int = 40) -> None:
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE offres(cle TEXT,entreprise TEXT,titre TEXT,note_json TEXT)")
    db.execute(
        """CREATE TABLE swelist_annonces(simplify_id TEXT PRIMARY KEY,intitule TEXT,
           label_humain INTEGER,score_fit REAL,verdict_ml TEXT,version_modele TEXT,
           evalue_le TEXT)"""
    )
    rows = []
    for c in range(companies):
        for i, (good, bad) in enumerate(zip(GOOD, BAD, strict=True)):
            rows.append((f"{c}-g{i}", f"Co{c}", f"{good} Intern {c}", {"notes": [5, 3, 3, 3]}))
            rows.append((f"{c}-b{i}", f"Co{c}", f"{bad} Intern {c}", {"notes": [1, 3, 3, 3]}))
    db.executemany(
        "INSERT INTO offres VALUES(?,?,?,?)",
        [(k, co, t, json.dumps(n)) for k, co, t, n in rows],
    )
    db.executemany(
        "INSERT INTO swelist_annonces(simplify_id,intitule,label_humain) VALUES(?,?,?)",
        [("s1", "Machine Learning Intern", 1), ("s2", "Mechanical Intern", None)],
    )
    db.commit()
    db.close()


class DatasetTests(unittest.TestCase):
    def setUp(self):
        if np is None:
            self.skipTest("dépendances ML absentes")

    def test_final_verdict_does_not_become_training_label(self):
        db = sqlite3.connect(":memory:")
        db.execute("CREATE TABLE offres(cle TEXT,entreprise TEXT,titre TEXT,note_json TEXT)")
        rows = [
            ("1", "A", "Software Engineer Intern", {"notes": [4, 1, 1, 1], "motif": "visa"}),
            ("2", "B", "Accountant Intern", {"notes": [1, 5, 5, 5], "statut": "gardee"}),
            ("3", "C", "Uncertain Intern", {"notes": [2, 5, 5, 5]}),
            ("4", "D", "Data Engineer Intern", {"notes": [4, 4, 4, 4]}),
            ("5", "E", "DATA engineer intern", {"notes": [1, 1, 1, 1]}),
        ]
        db.executemany(
            "INSERT INTO offres VALUES(?,?,?,?)",
            [(key, company, title, json.dumps(note)) for key, company, title, note in rows],
        )
        examples, stats = load_examples(db)
        self.assertEqual({x.key: x.label for x in examples}, {"1": 1, "2": 0})
        self.assertEqual(stats["conflicting_titles"], 2)

    def test_majority_label_keeps_frequent_title(self):
        db = sqlite3.connect(":memory:")
        db.execute("CREATE TABLE offres(cle TEXT,entreprise TEXT,titre TEXT,note_json TEXT)")
        grades = [("1", 4), ("2", 5), ("3", 1)]
        db.executemany(
            "INSERT INTO offres VALUES(?,?,?,?)",
            [(k, k, "Software Engineer Intern", json.dumps({"notes": [g]})) for k, g in grades],
        )
        examples, stats = load_examples(db)
        self.assertEqual([(x.key, x.label) for x in examples], [("1", 1)])
        self.assertEqual(stats["majority_resolved_titles"], 1)

    def test_splits_share_no_company(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry(Path(tmp) / "r.sqlite")
            db = sqlite3.connect(Path(tmp) / "r.sqlite")
            examples, _ = load_examples(db)
            db.close()
        split = split_company(examples)
        names = [{x.company for x in rows} for rows in split.values()]
        self.assertFalse(names[0] & names[1] or names[0] & names[2] or names[1] & names[2])


class ModelTests(unittest.TestCase):
    def setUp(self):
        if np is None:
            self.skipTest("dépendances ML absentes")

    def test_frozen_tfidf_matches_sklearn(self):
        titles = [f"{g} Intern" for g in GOOD + BAD] * 2
        model = TitleModel().fit(titles, [1] * 5 + [0] * 5 + [1] * 5 + [0] * 5, fake_embed)
        reference = TfidfVectorizer(
            analyzer="char_wb", ngram_range=CHAR_NGRAMS, sublinear_tf=True, min_df=2
        ).fit([t.lower() for t in titles])
        ours = model._tfidf(["Software Engineer Intern"]).toarray()
        theirs = reference.transform(["software engineer intern"]).toarray()
        self.assertTrue(np.allclose(ours, theirs))

    def test_artifact_reproduces_scores(self):
        titles = [f"{g} Intern" for g in GOOD + BAD] * 2
        labels = [1] * 5 + [0] * 5 + [1] * 5 + [0] * 5
        model = TitleModel().fit(titles, labels, fake_embed)
        reloaded = TitleModel.from_artifact(json.loads(json.dumps(model.to_artifact())))
        probe = ["Applied ML Intern", "Mechanical Design Intern"]
        self.assertTrue(
            np.allclose(model.score(probe, fake_embed), reloaded.score(probe, fake_embed))
        )

    def test_train_then_score_keeps_labels_and_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path, model_path = Path(tmp) / "r.sqlite", Path(tmp) / "m.json"
            registry(db_path)
            before = query(db_path, "SELECT * FROM offres")
            report = train(
                db_path, model_path, Path(tmp) / "r.json", Path(tmp) / "e.csv", fake_embed
            )
            self.assertGreater(report["developpement_hors_pli"]["auc"], 0.9)
            self.assertEqual(query(db_path, "SELECT * FROM offres"), before)
            labels = dict(query(db_path, "SELECT simplify_id,label_humain FROM swelist_annonces"))
            self.assertEqual(labels, {"s1": 1, "s2": None})
            first = dict(query(db_path, "SELECT simplify_id,score_fit FROM swelist_annonces"))
            db = sqlite3.connect(db_path)
            with db:
                db.execute(
                    "INSERT INTO swelist_annonces(simplify_id,intitule) VALUES('s3','Data Intern')"
                )
            db.close()
            result = score_only(db_path, model_path, fake_embed)
            self.assertEqual(result["notees"], 1)  # seule la nouvelle annonce est notée
            after = dict(query(db_path, "SELECT simplify_id,score_fit FROM swelist_annonces"))
            self.assertEqual({k: after[k] for k in first}, first)
            self.assertIsNotNone(after["s3"])


if __name__ == "__main__":
    unittest.main()
