import csv
import sqlite3
import tempfile
import unittest
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from mails_swelist import date_depart, message_depuis_brut, traiter

UUID1 = "11111111-2222-3333-4444-555555555555"
UUID2 = "66666666-7777-8888-9999-000000000000"


def mail(sujet, annonces):
    html = "".join(
        f'<p class="internship"><strong>{e}:</strong> '
        f'<a href="https://simplify.jobs/p/{u}?utm_source=swelist">{t}</a></p>'
        for e, t, u in annonces
    )
    message = MIMEMultipart("alternative")
    message["Subject"] = sujet
    message["From"] = "SWE List <noreply@swelist.com>"
    message["Date"] = "Fri, 16 Oct 2026 07:00:00 +0000"
    message.attach(MIMEText("version texte", "plain"))
    message.attach(MIMEText(html, "html", "utf-8"))
    return message.as_bytes()


class MailsSwelistTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        db = sqlite3.connect(self.dir / "r.sqlite")
        db.execute(
            "CREATE TABLE offres(cle TEXT PRIMARY KEY, entreprise TEXT, titre TEXT, url TEXT)"
        )
        db.commit()
        db.close()

    def test_mail_brut_devient_annonces_puis_import(self):
        brut = mail(
            "2 New Internships Posted Today",
            [("Acme", "ML Engineer Intern", UUID1), ("Beta", "SWE Intern", UUID2)],
        )
        message = message_depuis_brut(brut, "19a2b3c4d5e6f708")
        self.assertEqual(message["date"], "2026-10-16")
        self.assertIn("internship", message["html"])
        inventaire = self.dir / "inventaire.csv"
        resultat = traiter([message], inventaire, self.dir / "r.sqlite")
        self.assertEqual(resultat["annonces_ajoutees"], 2)
        self.assertEqual(resultat["mails_en_erreur"], [])
        # Relire le même mail ne crée aucun doublon.
        self.assertEqual(
            traiter([message], inventaire, self.dir / "r.sqlite")["annonces_ajoutees"], 0
        )
        db = sqlite3.connect(self.dir / "r.sqlite")
        n = db.execute("SELECT count(*) FROM swelist_annonces").fetchone()[0]
        db.close()
        self.assertEqual(n, 2)

    def test_mail_incoherent_signale_sans_bloquer_les_autres(self):
        bon = message_depuis_brut(
            mail("1 New Internships Posted Today", [("Acme", "AI Intern", UUID1)]), "a1"
        )
        faux = message_depuis_brut(
            mail("5 New Internships Posted Today", [("Beta", "X", UUID2)]), "b2"
        )
        resultat = traiter([faux, bon], self.dir / "inv.csv", self.dir / "r.sqlite")
        self.assertEqual(resultat["annonces_ajoutees"], 1)
        self.assertEqual([e["id"] for e in resultat["mails_en_erreur"]], ["b2"])

    def test_date_depart(self):
        inventaire = self.dir / "inv.csv"
        with inventaire.open("w", encoding="utf-8", newline="") as fichier:
            writer = csv.writer(fichier, quoting=csv.QUOTE_ALL)
            writer.writerow(["date_mail", "id_mail"])
            writer.writerow(["2026-10-10", "x"])
            writer.writerow(["2026-10-15", "y"])
        self.assertEqual(date_depart(inventaire), date(2026, 10, 13))


if __name__ == "__main__":
    unittest.main()
