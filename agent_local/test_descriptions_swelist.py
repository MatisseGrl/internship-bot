import json
import sqlite3
import unittest

from descriptions_swelist import Blocked, parse_page, pending, run


def page(description="<p>Build <b>ML</b> models</p><ul><li>Python</li></ul>", active=True):
    data = {
        "props": {
            "pageProps": {
                "jobPosting": {
                    "description": description,
                    "active": active,
                    "requirements": ["Python"],
                    "responsibilities": ["Train models"],
                    "locations": [{"value": "Paris"}],
                    "tracked_obj": "greenhouse:acme/jobs/1",
                }
            }
        }
    }
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'


def registry():
    db = sqlite3.connect(":memory:")
    db.execute(
        """CREATE TABLE swelist_annonces(simplify_id TEXT PRIMARY KEY, lien_simplify TEXT,
           verdict_ml TEXT, score_fit REAL)"""
    )
    db.executemany(
        "INSERT INTO swelist_annonces VALUES(?,?,?,?)",
        [
            ("low", "https://simplify.jobs/p/low", "basse_priorite_a_relire", 0.05),
            ("mid", "https://simplify.jobs/p/mid", "a_lire", 0.5),
            ("top2", "https://simplify.jobs/p/top2", "prioriser", 0.8),
            ("top1", "https://simplify.jobs/p/top1", "prioriser", 0.95),
        ],
    )
    return db


class DescriptionTests(unittest.TestCase):
    def test_parse_keeps_structure_and_plain_text(self):
        fields = parse_page(page())
        self.assertEqual(fields["description_texte"], "Build ML models\nPython")
        self.assertEqual(json.loads(fields["exigences"]), ["Python"])
        self.assertEqual(json.loads(fields["lieux"]), ["Paris"])
        self.assertEqual(fields["actif"], 1)
        with self.assertRaises(ValueError):
            parse_page("<html>no data</html>")

    def test_priority_order_then_resume(self):
        db = registry()
        seen = []

        def fetch(url):
            seen.append(url.rsplit("/", 1)[1])
            return 200, page()

        stats = run(db, limit=2, delay=0, fetch=fetch, sleep=lambda _: None, log=lambda _: None)
        self.assertEqual(seen, ["top1", "top2"])
        self.assertEqual(stats["ok"], 2)
        self.assertEqual([sid for sid, _ in pending(db)], ["mid", "low"])
        run(db, limit=None, delay=0, fetch=fetch, sleep=lambda _: None, log=lambda _: None)
        self.assertEqual(seen, ["top1", "top2", "mid", "low"])

    def test_block_stops_without_retry(self):
        db = registry()
        calls = []

        def fetch(url):
            calls.append(url)
            return 403, ""

        with self.assertRaises(Blocked):
            run(db, limit=None, delay=0, fetch=fetch, sleep=lambda _: None, log=lambda _: None)
        self.assertEqual(len(calls), 1)

    def test_missing_page_is_not_retried(self):
        db = registry()
        run(db, 1, 0, fetch=lambda u: (404, ""), sleep=lambda _: None, log=lambda _: None)
        self.assertNotIn("top1", [sid for sid, _ in pending(db)])


if __name__ == "__main__":
    unittest.main()
