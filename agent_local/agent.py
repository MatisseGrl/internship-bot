"""Orchestrateur local et privé des candidatures, sans action dans le navigateur.

Le navigateur est piloté par Codex à partir des dossiers produits ici. Une offre
ne peut être déclarée envoyée qu'avec une preuve explicite de réception.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sqlite3
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from suivi_candidatures import cle, maintenant, ouvrir, synchroniser

SCHEMA_AGENT = """
CREATE TABLE IF NOT EXISTS sources_offres (
    source TEXT NOT NULL,
    identifiant_source TEXT NOT NULL,
    cle_offre TEXT NOT NULL REFERENCES offres(cle),
    url_canonique TEXT,
    vu_le TEXT NOT NULL,
    PRIMARY KEY(source, identifiant_source)
);
CREATE INDEX IF NOT EXISTS idx_sources_url ON sources_offres(url_canonique);
CREATE TABLE IF NOT EXISTS decisions (
    cle_offre TEXT PRIMARY KEY REFERENCES offres(cle),
    etat TEXT NOT NULL,
    raison TEXT NOT NULL DEFAULT '',
    cv TEXT,
    dossier_json TEXT,
    relu_le TEXT,
    modifie_le TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tentatives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cle_offre TEXT NOT NULL REFERENCES offres(cle),
    commence_le TEXT NOT NULL,
    terminee_le TEXT,
    resultat TEXT,
    preuve TEXT,
    UNIQUE(cle_offre)
);
CREATE TABLE IF NOT EXISTS journal_agent (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cle_offre TEXT REFERENCES offres(cle),
    evenement TEXT NOT NULL,
    detail TEXT NOT NULL,
    cree_le TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS couts_agent (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mois TEXT NOT NULL,
    cout_micro_usd INTEGER NOT NULL CHECK(cout_micro_usd >= 0),
    usage TEXT NOT NULL,
    cree_le TEXT NOT NULL
);
"""

ETATS = {
    "a_qualifier",
    "a_verifier",
    "hors_cible",
    "inelegible",
    "prete_a_remplir",
    "formulaire_en_cours",
    "prete_a_envoyer",
    "envoi_en_cours",
    "envoyee",
    "refusee",
    "entretien",
    "evaluation",
    "action_requise",
    "bloquee",
}
TERMINAUX = {"envoyee", "refusee", "entretien", "evaluation", "envoi_en_cours"}
LIMITE_MICRO_USD = 9_000_000  # marge sous le plafond de 10 USD/mois
TRACKING = {"gclid", "fbclid", "mc_cid", "mc_eid", "ref", "source"}


def initialiser(db: sqlite3.Connection) -> None:
    db.executescript(SCHEMA_AGENT)


def profil() -> dict:
    chemin = os.environ.get("INTERNBOT_PROFILE")
    if not chemin:
        raise ValueError("Définir INTERNBOT_PROFILE vers le profil privé hors du dépôt")
    return json.loads(Path(chemin).read_text(encoding="utf-8"))


def url_canonique(url: str) -> str:
    """Supprime uniquement le suivi marketing ; conserve les paramètres d'offre."""
    morceaux = urlsplit(url.strip())
    if morceaux.scheme not in {"http", "https"} or not morceaux.hostname:
        raise ValueError("URL d'offre invalide")
    params = [
        (k, v)
        for k, v in parse_qsl(morceaux.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in TRACKING
    ]
    return urlunsplit(
        (
            morceaux.scheme.lower(),
            morceaux.netloc.lower(),
            morceaux.path.rstrip("/") or "/",
            urlencode(params),
            "",
        )
    )


def _chaine(valeur: object) -> str:
    return str(valeur).strip() if valeur is not None else ""


def _champ(entree: dict, *noms: str) -> str:
    normalisee = {str(k).strip().casefold(): v for k, v in entree.items()}
    for nom in noms:
        valeur = _chaine(normalisee.get(nom.casefold()))
        if valeur:
            return valeur
    return ""


def importer_simplify(db: sqlite3.Connection, chemin: Path) -> dict[str, int]:
    """Importe un export personnel CSV/JSON de Simplify, sans accès au compte.

    Un export sans URL reste dans le registre pour anti-doublon et revue ; il
    n'entre jamais dans une candidature automatique.
    """
    if chemin.suffix.lower() == ".csv":
        with chemin.open(encoding="utf-8-sig", newline="") as fichier:
            entrees = list(csv.DictReader(fichier))
    elif chemin.suffix.lower() == ".json":
        entrees = json.loads(chemin.read_text(encoding="utf-8-sig"))
        if isinstance(entrees, dict):
            entrees = entrees.get("jobs", entrees.get("offres"))
    else:
        raise ValueError("Export attendu en CSV ou JSON")
    if not isinstance(entrees, list):
        raise ValueError("L'export doit contenir une liste d'offres")
    compte = {"lues": 0, "ajoutees": 0, "rapprochees": 0, "ignorees": 0}
    urls_connues = {}
    for ligne in db.execute("SELECT cle,url FROM offres WHERE url IS NOT NULL"):
        with suppress(ValueError):
            urls_connues[url_canonique(ligne["url"])] = ligne["cle"]
    with db:
        for entree in entrees:
            compte["lues"] += 1
            if not isinstance(entree, dict):
                compte["ignorees"] += 1
                continue
            entreprise = _champ(entree, "company", "company name", "entreprise")
            titre = _champ(entree, "title", "position title", "position", "titre", "role")
            url = _champ(entree, "url", "link", "job url", "job link", "application url")
            if not entreprise or not titre:
                compte["ignorees"] += 1
                continue
            try:
                canonique = url_canonique(url) if url else None
            except ValueError:
                canonique = None
            identifiant = _champ(entree, "job_id", "job id", "id")
            if not identifiant:
                identifiant = hashlib.sha256(
                    (
                        canonique
                        or "\x1f".join(
                            (
                                entreprise.casefold(),
                                titre.casefold(),
                                _champ(entree, "location", "lieu").casefold(),
                            )
                        )
                    ).encode()
                ).hexdigest()[:20]
            identifiant_source = f"{entreprise}\x1f{identifiant}"
            ligne = (
                db.execute(
                    "SELECT cle_offre FROM sources_offres WHERE url_canonique=? LIMIT 1",
                    (canonique,),
                ).fetchone()
                if canonique
                else None
            )
            if not ligne:
                ligne = db.execute(
                    "SELECT cle FROM offres WHERE entreprise=? AND identifiant=? LIMIT 1",
                    (entreprise, identifiant),
                ).fetchone()
                cle_offre = (
                    ligne[0] if ligne else urls_connues.get(canonique, cle(entreprise, identifiant))
                )
            else:
                cle_offre = ligne[0]
            existe = db.execute("SELECT 1 FROM offres WHERE cle=?", (cle_offre,)).fetchone()
            if not existe:
                db.execute(
                    """INSERT INTO offres(cle,entreprise,identifiant,titre,lieu,url,texte,vu_le)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (
                        cle_offre,
                        entreprise,
                        identifiant,
                        titre,
                        _champ(entree, "location", "lieu"),
                        url or None,
                        _champ(entree, "description", "job description", "texte"),
                        maintenant(),
                    ),
                )
                compte["ajoutees"] += 1
                if canonique:
                    urls_connues[canonique] = cle_offre
            else:
                compte["rapprochees"] += 1
            db.execute(
                """INSERT INTO sources_offres
                   (source,identifiant_source,cle_offre,url_canonique,vu_le)
                   VALUES('simplify',?,?,?,?) ON CONFLICT(source,identifiant_source)
                   DO UPDATE SET cle_offre=excluded.cle_offre,
                   url_canonique=excluded.url_canonique,vu_le=excluded.vu_le""",
                (identifiant_source, cle_offre, canonique, maintenant()),
            )
            statut_simplify = _champ(entree, "application status", "status", "stage").casefold()
            statut = {
                "applied": "envoyee",
                "submitted": "envoyee",
                "interview": "entretien",
                "interviewing": "entretien",
                "rejected": "refusee",
                "declined": "refusee",
                "candidature envoyée": "envoyee",
                "refusée": "refusee",
                "entretien": "entretien",
            }.get(statut_simplify)
            if statut:
                precedent = _etat_candidature(db, cle_offre)
                # Ne jamais rétrograder un état connu par un export potentiellement ancien.
                if precedent not in {"refusee", "entretien", "evaluation", "action_requise"}:
                    db.execute(
                        """INSERT INTO candidatures(cle_offre,statut,preuve,modifie_le)
                           VALUES(?,?,?,?) ON CONFLICT(cle_offre) DO UPDATE SET
                           statut=excluded.statut,preuve=excluded.preuve,modifie_le=excluded.modifie_le""",
                        (
                            cle_offre,
                            statut,
                            f"simplify-export:{chemin.name}:{compte['lues']}",
                            maintenant(),
                        ),
                    )
    return compte


def _etat_candidature(db: sqlite3.Connection, cle_offre: str) -> str | None:
    ligne = db.execute("SELECT statut FROM candidatures WHERE cle_offre=?", (cle_offre,)).fetchone()
    return ligne[0] if ligne else None


def classer(db: sqlite3.Connection) -> dict[str, int]:
    """Classe les exclusions certaines ; garde les autres pour jugement par offre."""
    compte = {"a_qualifier": 0, "inelegible": 0, "a_verifier": 0, "deja_traitees": 0}
    lignes = db.execute(
        """SELECT o.*, EXISTS(SELECT 1 FROM sources_offres s WHERE s.cle_offre=o.cle)
           AS depuis_simplify FROM offres o WHERE o.dans_snapshot=1 OR depuis_simplify=1"""
    ).fetchall()
    with db:
        for offre in lignes:
            statut_candidature = _etat_candidature(db, offre["cle"])
            if statut_candidature in TERMINAUX:
                compte["deja_traitees"] += 1
                continue
            deja = db.execute(
                "SELECT etat FROM decisions WHERE cle_offre=?", (offre["cle"],)
            ).fetchone()
            if deja:
                continue
            note = json.loads(offre["note_json"]) if offre["note_json"] else {}
            motif = note.get("motif") if isinstance(note, dict) else None
            # Une exclusion de qualité historique n'est pas une inéligibilité.
            if statut_candidature == "action_requise":
                etat, raison = (
                    "action_requise",
                    "Courriel demandant une action ou une nouvelle candidature",
                )
            elif offre["categorie_note"] == "ecartee" and motif in {
                "fin_etudes",
                "niveau",
                "phd",
                "fermee",
                "nationalite",
                "dates",
            }:
                etat, raison = "inelegible", f"Note historique : {motif}"
            elif not offre["texte"] or not offre["url"]:
                etat, raison = "a_verifier", "Texte intégral ou URL d'offre manquant"
            else:
                etat, raison = "a_qualifier", "Lecture détaillée requise"
            db.execute(
                "INSERT INTO decisions(cle_offre,etat,raison,modifie_le) VALUES(?,?,?,?)",
                (offre["cle"], etat, raison, maintenant()),
            )
            compte[etat] = compte.get(etat, 0) + 1
    return compte


def reconcilier(db: sqlite3.Connection) -> int:
    """Report d'un statut confirmé par mail/export dans la file de décisions."""
    changements = 0
    lignes = db.execute(
        """SELECT c.cle_offre,c.statut,c.preuve,d.etat FROM candidatures c
           LEFT JOIN decisions d ON d.cle_offre=c.cle_offre"""
    ).fetchall()
    with db:
        for ligne in lignes:
            statut = ligne["statut"]
            if statut not in ETATS or statut == ligne["etat"]:
                continue
            # Une preuve de candidature déjà envoyée prime sur une file de préparation.
            if statut == "envoyee" and ligne["etat"] in {
                "refusee",
                "entretien",
                "evaluation",
                "action_requise",
            }:
                continue
            db.execute(
                """INSERT INTO decisions(cle_offre,etat,raison,modifie_le)
                   VALUES(?,?,?,?) ON CONFLICT(cle_offre) DO UPDATE SET
                   etat=excluded.etat,raison=excluded.raison,modifie_le=excluded.modifie_le""",
                (
                    ligne["cle_offre"],
                    statut,
                    f"Statut confirmé : {ligne['preuve'] or 'registre'}",
                    maintenant(),
                ),
            )
            db.execute(
                "INSERT INTO journal_agent(cle_offre,evenement,detail,cree_le) VALUES(?,?,?,?)",
                (ligne["cle_offre"], "rapprochement", statut, maintenant()),
            )
            changements += 1
    return changements


def file(db: sqlite3.Connection, limite: int = 20) -> list[dict]:
    lignes = db.execute(
        """SELECT o.cle,o.entreprise,o.identifiant,o.titre,o.lieu,o.url,o.score,
                  o.categorie_note,d.etat,d.raison,
                  EXISTS(SELECT 1 FROM sources_offres s WHERE s.cle_offre=o.cle) AS simplify
           FROM decisions d JOIN offres o ON o.cle=d.cle_offre
           WHERE d.etat IN ('a_qualifier','a_verifier','prete_a_remplir','action_requise')
             AND NOT EXISTS(SELECT 1 FROM tentatives t WHERE t.cle_offre=o.cle)
           ORDER BY CASE d.etat WHEN 'action_requise' THEN 0 WHEN 'prete_a_remplir' THEN 1
                     WHEN 'a_qualifier' THEN 2 ELSE 3 END,
                    o.dans_snapshot DESC, COALESCE(o.score,0) DESC, o.entreprise
           LIMIT ?""",
        (limite,),
    ).fetchall()
    return [dict(x) for x in lignes]


def dossier(db: sqlite3.Connection, entreprise: str, identifiant: str) -> dict:
    ligne = db.execute(
        """SELECT o.*,d.etat,d.raison,d.cv,d.dossier_json,c.statut AS statut_candidature
           FROM offres o LEFT JOIN decisions d ON d.cle_offre=o.cle
           LEFT JOIN candidatures c ON c.cle_offre=o.cle
           WHERE o.entreprise=? AND o.identifiant=?""",
        (entreprise, identifiant),
    ).fetchone()
    if not ligne:
        raise ValueError("Offre introuvable")
    note = json.loads(ligne["note_json"]) if ligne["note_json"] else None
    return {
        "entreprise": ligne["entreprise"],
        "identifiant": ligne["identifiant"],
        "titre": ligne["titre"],
        "lieu": ligne["lieu"],
        "url": ligne["url"],
        "texte": ligne["texte"],
        "note_historique": note,
        "score_historique": ligne["score"],
        "etat": ligne["etat"],
        "raison": ligne["raison"],
        "cv": ligne["cv"],
        "statut_candidature": ligne["statut_candidature"],
        "decision": json.loads(ligne["dossier_json"]) if ligne["dossier_json"] else None,
        "faits_candidat": profil()["faits"],
        "consignes": [
            "Vérifier l'éligibilité dans le texte actuel avant de postuler.",
            "Choisir un CV officiel selon le pays et l'offre ; vérifier son contenu.",
            "Rédiger des réponses propres à cette offre à partir de faits vérifiés.",
            profil().get("connexion", "Vérifier la méthode de connexion avec le candidat."),
            "Les 15 premières candidatures nécessitent une revue avant envoi.",
            "Une tentative sans confirmation reste à vérifier ; ne pas renvoyer automatiquement.",
        ],
    }


def decider(db: sqlite3.Connection, entreprise: str, identifiant: str, decision: dict) -> None:
    """Une décision IA/humaine doit citer l'annonce et ne choisit pas le CV par défaut."""
    cle_offre = cle(entreprise, identifiant)
    offre = db.execute("SELECT texte FROM offres WHERE cle=?", (cle_offre,)).fetchone()
    if not offre:
        raise ValueError("Offre introuvable")
    etat = decision.get("etat")
    if etat not in {"prete_a_remplir", "a_verifier", "inelegible", "hors_cible"}:
        raise ValueError("Décision invalide")
    raison = _chaine(decision.get("raison"))
    citation = _chaine(decision.get("citation_annonce"))
    if not raison or not citation or citation not in (offre["texte"] or ""):
        raise ValueError("Raison et citation exacte de l'annonce requises")
    cv = _chaine(decision.get("cv")) or None
    if etat == "prete_a_remplir":
        if cv not in profil()["cv"]:
            raise ValueError("Choisir un CV officiel explicite")
        if not _chaine(decision.get("justification_cv")):
            raise ValueError("Justification du CV requise")
        arguments = decision.get("arguments")
        faits = profil()["faits"]
        if not isinstance(arguments, list) or not arguments:
            raise ValueError("Au moins un argument propre à l'offre est requis")
        for argument in arguments:
            if not isinstance(argument, dict) or (
                not _chaine(argument.get("citation_annonce"))
                or _chaine(argument.get("citation_annonce")) not in (offre["texte"] or "")
                or argument.get("fait_cv") not in faits
                or not _chaine(argument.get("usage"))
            ):
                raise ValueError("Argument sans citation exacte, fait CV ou usage")
    with db:
        ancienne = db.execute(
            "SELECT etat FROM decisions WHERE cle_offre=?", (cle_offre,)
        ).fetchone()
        if ancienne and ancienne[0] in {"envoi_en_cours", "envoyee", "refusee"}:
            raise ValueError("Candidature déjà en cours ou envoyée")
        db.execute(
            """INSERT INTO decisions(cle_offre,etat,raison,cv,dossier_json,modifie_le)
               VALUES(?,?,?,?,?,?) ON CONFLICT(cle_offre) DO UPDATE SET
               etat=excluded.etat,raison=excluded.raison,cv=excluded.cv,
               dossier_json=excluded.dossier_json,modifie_le=excluded.modifie_le""",
            (cle_offre, etat, raison, cv, json.dumps(decision, ensure_ascii=False), maintenant()),
        )
        db.execute(
            "INSERT INTO journal_agent(cle_offre,evenement,detail,cree_le) VALUES(?,?,?,?)",
            (cle_offre, "decision", raison, maintenant()),
        )


def etape_formulaire(
    db: sqlite3.Connection, entreprise: str, identifiant: str, nouvel_etat: str, preuve: str = ""
) -> None:
    """Transitions serrées ; début d'envoi crée un verrou durable anti-doublon."""
    cle_offre = cle(entreprise, identifiant)
    precedents = {
        "formulaire_en_cours": {"prete_a_remplir"},
        "prete_a_envoyer": {"formulaire_en_cours"},
        "envoi_en_cours": {"prete_a_envoyer"},
        "envoyee": {"envoi_en_cours"},
        "a_verifier": {"formulaire_en_cours", "prete_a_envoyer", "envoi_en_cours"},
        "bloquee": {"formulaire_en_cours", "prete_a_envoyer"},
    }
    if nouvel_etat not in precedents:
        raise ValueError("Étape de formulaire inconnue")
    with db:
        ligne = db.execute(
            "SELECT etat, relu_le FROM decisions WHERE cle_offre=?", (cle_offre,)
        ).fetchone()
        if not ligne or ligne["etat"] not in precedents[nouvel_etat]:
            raise ValueError("Transition non autorisée")
        if nouvel_etat == "envoi_en_cours":
            # Le pilote exige une revue explicite des quinze premières candidatures.
            nombre = db.execute("SELECT count(*) FROM tentatives").fetchone()[0]
            if nombre < 15 and not ligne["relu_le"]:
                raise ValueError("Revue des 15 premières candidatures requise")
            db.execute(
                "INSERT INTO tentatives(cle_offre,commence_le) VALUES(?,?)",
                (cle_offre, maintenant()),
            )
        if nouvel_etat == "envoyee" and not preuve.strip():
            raise ValueError("Preuve de réception requise")
        if nouvel_etat == "envoyee":
            db.execute(
                """UPDATE tentatives SET terminee_le=?,resultat='confirmee',preuve=?
                   WHERE cle_offre=?""",
                (maintenant(), preuve, cle_offre),
            )
            db.execute(
                """INSERT INTO candidatures(cle_offre,statut,preuve,modifie_le)
                   VALUES(?,'envoyee',?,?) ON CONFLICT(cle_offre) DO UPDATE SET
                   statut='envoyee',preuve=excluded.preuve,modifie_le=excluded.modifie_le""",
                (cle_offre, preuve, maintenant()),
            )
        if nouvel_etat == "a_verifier" and ligne["etat"] == "envoi_en_cours":
            db.execute(
                """UPDATE tentatives SET terminee_le=?,resultat='incertaine',preuve=?
                   WHERE cle_offre=?""",
                (maintenant(), preuve or None, cle_offre),
            )
        db.execute(
            "UPDATE decisions SET etat=?,modifie_le=? WHERE cle_offre=?",
            (nouvel_etat, maintenant(), cle_offre),
        )
        db.execute(
            "INSERT INTO journal_agent(cle_offre,evenement,detail,cree_le) VALUES(?,?,?,?)",
            (cle_offre, nouvel_etat, preuve, maintenant()),
        )


def marquer_relu(db: sqlite3.Connection, entreprise: str, identifiant: str) -> None:
    with db:
        curseur = db.execute(
            """UPDATE decisions SET relu_le=?,modifie_le=? WHERE cle_offre=?
               AND etat='prete_a_envoyer'""",
            (maintenant(), maintenant(), cle(entreprise, identifiant)),
        )
        if curseur.rowcount != 1:
            raise ValueError("Formulaire non prêt à envoyer")


def budget_disponible(db: sqlite3.Connection, estimation_micro_usd: int) -> bool:
    mois = datetime.now(UTC).strftime("%Y-%m")
    depense = db.execute(
        "SELECT COALESCE(sum(cout_micro_usd),0) FROM couts_agent WHERE mois=?", (mois,)
    ).fetchone()[0]
    return estimation_micro_usd >= 0 and depense + estimation_micro_usd <= LIMITE_MICRO_USD


def main() -> None:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--db", type=Path, default=Path(__file__).with_name("suivi.sqlite"))
    sous = parseur.add_subparsers(dest="commande", required=True)
    sync = sous.add_parser("sync-bot")
    sync.add_argument("--snapshot", type=Path, required=True)
    sync.add_argument("--notes", type=Path, required=True)
    sync.add_argument("--archives", type=Path, nargs="*", default=[])
    imp = sous.add_parser("import-simplify")
    imp.add_argument("export", type=Path)
    sous.add_parser("classer")
    sous.add_parser("reconcilier")
    fl = sous.add_parser("file")
    fl.add_argument("--limite", type=int, default=20)
    dos = sous.add_parser("dossier")
    dos.add_argument("entreprise")
    dos.add_argument("identifiant")
    dec = sous.add_parser("decider")
    dec.add_argument("entreprise")
    dec.add_argument("identifiant")
    dec.add_argument("json", type=Path)
    et = sous.add_parser("etape")
    et.add_argument("entreprise")
    et.add_argument("identifiant")
    et.add_argument("etat", choices=sorted(ETATS))
    et.add_argument("--preuve", default="")
    rel = sous.add_parser("relu")
    rel.add_argument("entreprise")
    rel.add_argument("identifiant")
    args = parseur.parse_args()
    db = ouvrir(args.db)
    try:
        initialiser(db)
        if args.commande == "sync-bot":
            resultat = synchroniser(
                db,
                json.loads(args.notes.read_text(encoding="utf-8-sig")),
                args.archives,
                json.loads(args.snapshot.read_text(encoding="utf-8-sig")),
            )
        elif args.commande == "import-simplify":
            resultat = importer_simplify(db, args.export)
        elif args.commande == "classer":
            resultat = classer(db)
        elif args.commande == "reconcilier":
            resultat = {"decisions_mises_a_jour": reconcilier(db)}
        elif args.commande == "file":
            resultat = file(db, args.limite)
        elif args.commande == "dossier":
            resultat = dossier(db, args.entreprise, args.identifiant)
        elif args.commande == "decider":
            decider(
                db,
                args.entreprise,
                args.identifiant,
                json.loads(args.json.read_text(encoding="utf-8")),
            )
            resultat = {"etat": "decision_enregistree"}
        elif args.commande == "relu":
            marquer_relu(db, args.entreprise, args.identifiant)
            resultat = {"etat": "relu"}
        else:
            etape_formulaire(db, args.entreprise, args.identifiant, args.etat, args.preuve)
            resultat = {"etat": args.etat}
        print(json.dumps(resultat, ensure_ascii=False, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
