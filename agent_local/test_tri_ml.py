import json
import sqlite3
import unittest

from tri_ml import load_examples


class DatasetTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
