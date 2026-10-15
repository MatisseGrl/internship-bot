"""Failure and replay checks for the private Supabase copier."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from sync_supabase import RestClient, SyncError, single_instance, sync


class FakeSupabase:
    def __init__(self):
        self.rows = {"offres": {}, "swelist_annonces": {}, "candidatures": {}, "mails": {}}
        self.calls = 0
        self.fail_on_call = None

    def upsert(self, table, rows):
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise SyncError("panne simulée")
        for row in rows:
            key = row.get("cle") or row.get("simplify_id") or row.get("cle_offre") or (
                row["boite"], row["identifiant_message"])
            self.rows[table][key] = row

    def count(self, table, where=""):
        rows = list(self.rows[table].values())
        if where == "&note_json=not.is.null":
            rows = [row for row in rows if row["note_json"] is not None]
        elif where == "&texte=not.is.null":
            rows = [row for row in rows if row["texte"] is not None]
        elif where == "&dans_snapshot=eq.true":
            rows = [row for row in rows if row["dans_snapshot"]]
        return len(rows)


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.db_path = Path(self.temp.name) / "source.sqlite"
        self.state_path = Path(self.temp.name) / "state.sqlite"
        with closing(sqlite3.connect(self.db_path)) as db:
            db.executescript("""
                CREATE TABLE offres(cle TEXT PRIMARY KEY, entreprise TEXT, identifiant TEXT,
                    titre TEXT, lieu TEXT, url TEXT, texte TEXT, categorie_note TEXT,
                    note_json TEXT, score REAL, dans_snapshot INTEGER, vu_le TEXT);
                CREATE TABLE candidatures(cle_offre TEXT PRIMARY KEY, statut TEXT,
                    cv TEXT, preuve TEXT, modifie_le TEXT);
                CREATE TABLE mails(boite TEXT, identifiant_message TEXT, recu_le TEXT,
                    expediteur TEXT, objet TEXT, categorie TEXT, cle_offre TEXT,
                    justification TEXT, traite_le TEXT, PRIMARY KEY(boite, identifiant_message));
            """)
            db.execute("""INSERT INTO offres VALUES
                ('Acme' || char(31) || '1','Acme','1','Stage',NULL,NULL,'Texte',
                 'gardee','{"score":80}',80,1,'2026-10-15T10:00:00+00:00')""")
            db.execute("""INSERT INTO candidatures VALUES
                ('Acme' || char(31) || '1','envoyee','CV privé.pdf','mail:boite:m1',
                 '2026-10-15T10:00:00+00:00')""")
            db.execute("""INSERT INTO mails VALUES
                ('boite','m1',NULL,'recruteur','Confirmation','confirmation',
                 'Acme' || char(31) || '1','identifiant exact',
                 '2026-10-15T10:00:00+00:00')""")
            db.commit()

    def test_retry_after_interruption_and_changed_row(self):
        remote = FakeSupabase()
        remote.fail_on_call = 2
        with self.assertRaises(SyncError):
            sync(self.db_path, self.state_path, remote, max_bytes=1024)
        self.assertEqual(len(remote.rows["offres"]), 1)
        remote.fail_on_call = None
        result = sync(self.db_path, self.state_path, remote)
        self.assertEqual(result["uploaded"], {"offres": 0, "candidatures": 1, "mails": 1})
        self.assertEqual(remote.rows["candidatures"]["Acme\x1f1"].get("cv"), None)
        self.assertEqual(sync(self.db_path, self.state_path, remote)["uploaded"],
                         {"offres": 0, "candidatures": 0, "mails": 0})
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute("UPDATE offres SET texte='Texte corrigé'")
            db.commit()
        self.assertEqual(sync(self.db_path, self.state_path, remote)["uploaded"]["offres"], 1)
        self.assertEqual(remote.rows["offres"]["Acme\x1f1"]["texte"], "Texte corrigé")

    def test_remote_loss_triggers_full_replay(self):
        remote = FakeSupabase()
        sync(self.db_path, self.state_path, remote)
        remote.rows["offres"].clear()
        remote.rows["candidatures"].clear()
        remote.rows["mails"].clear()
        result = sync(self.db_path, self.state_path, remote)
        self.assertTrue(result["counts_verified"])
        self.assertEqual(result["uploaded"], {"offres": 1, "candidatures": 1, "mails": 1})

    def test_separate_swelist_rows_are_copied_without_becoming_bot_offers(self):
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute("""CREATE TABLE swelist_annonces(
                simplify_id TEXT PRIMARY KEY,date_mail TEXT,id_mail TEXT,entreprise TEXT,
                intitule TEXT,lien_simplify TEXT,premier_filtre TEXT,raison TEXT,
                bot_cle_candidate TEXT,rapprochement TEXT,label_humain INTEGER,
                score_fit REAL,verdict_ml TEXT,version_modele TEXT,evalue_le TEXT)""")
            db.execute("""INSERT INTO swelist_annonces VALUES
                ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa','2026-10-15','mail-1','Acme',
                 'Stage','https://simplify.jobs/p/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                 'a_revoir','ambigu','Acme' || char(31) || '1','titre_entreprise_unique',
                 NULL,0.8,'prioriser','titre-logreg-v1',NULL)""")
            db.commit()
        remote = FakeSupabase()
        result = sync(self.db_path, self.state_path, remote)
        self.assertEqual(result["uploaded"]["swelist_annonces"], 1)
        self.assertEqual(len(remote.rows["offres"]), 1)
        self.assertEqual(len(remote.rows["swelist_annonces"]), 1)

    def test_extra_remote_row_is_reported(self):
        remote = FakeSupabase()
        sync(self.db_path, self.state_path, remote)
        remote.rows["offres"]["other"] = dict(remote.rows["offres"]["Acme\x1f1"])
        with self.assertRaisesRegex(SyncError, "Comptes Supabase divergents"):
            sync(self.db_path, self.state_path, remote)

    def test_second_process_cannot_start_while_first_holds_lock(self):
        with single_instance(self.state_path):
            with self.assertRaisesRegex(SyncError, "déjà en cours"):
                with single_instance(self.state_path):
                    pass

    def test_rest_uses_secret_header_and_composite_upsert(self):
        class Response:
            def __init__(self):
                self.headers = Message()
                self.headers["Content-Range"] = "0-1/2"

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        requests = []

        def urlopen(request, timeout):
            requests.append(request)
            return Response()

        client = RestClient("https://example.supabase.co", "sb_secret_test")
        with patch("sync_supabase.urllib.request.urlopen", side_effect=urlopen):
            client.upsert("mails", [{"boite": "a", "identifiant_message": "b"}])
            self.assertEqual(client.count("mails"), 2)
            client.upsert("candidatures", [{"cle_offre": "Acme\x1f1", "statut": "envoyee"}])
        self.assertEqual(requests[0].get_method(), "POST")
        self.assertIn("on_conflict=boite,identifiant_message", requests[0].full_url)
        self.assertEqual(requests[0].get_header("Apikey"), "sb_secret_test")
        self.assertIsNone(requests[0].get_header("Authorization"))
        self.assertEqual(requests[1].get_method(), "HEAD")
        self.assertEqual(requests[2].get_method(), "POST")
        self.assertIn("resolution=ignore-duplicates", requests[2].get_header("Prefer"))
        self.assertEqual(requests[3].get_method(), "PATCH")
        self.assertIn("cle_offre=eq.Acme%1F1", requests[3].full_url)

    def test_publishable_key_is_rejected_before_network(self):
        with self.assertRaisesRegex(ValueError, "sb_secret_"):
            RestClient("https://example.supabase.co", "sb_publishable_test")


if __name__ == "__main__":
    unittest.main()
