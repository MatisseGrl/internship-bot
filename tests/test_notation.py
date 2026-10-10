from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from internbot.errors import ConfigError
from internbot.notation import (
    ECARTEE,
    LIMITE,
    RETENUE,
    VARIANTES,
    Entreprise,
    Notation,
    citation_presente,
    evaluer,
    importer,
    load_entreprises,
    score,
    verdict,
)

ROOT = Path(__file__).resolve().parent.parent

TEXTE = (
    "Machine Learning Intern - Perception\n"
    "Location: Mountain View, CA\n"
    "You will train and evaluate object detection models and deploy them to our robots.\n"
    "You will be paired with a dedicated mentor and present your work at the end.\n"
    "This internship is open to students graduating in 2028."
)
OFFRE = {
    "company": "Acme",
    "job_id": "1",
    "title": "ML Intern",
    "location": "Mountain View, CA",
    "texte": TEXTE,
}
ACME = Entreprise(eco=4, eco_preuve="startup IA", pont=3, pont_preuve="bureau à NYC")


def note(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "company": "Acme",
        "job_id": "1",
        "eligible": True,
        "stage": True,
        "lieu_us": False,
        "fit": 5,
        "preuve_fit": "train and evaluate object detection models",
        "app": 5,
        "preuve_app": "paired with a dedicated mentor",
        "conditions": "Été 2027",
    }
    base.update(kw)
    return base


def notes(fit: int, eco: int, pont: int, app: int) -> dict[str, int]:
    return {"fit": fit, "eco": eco, "pont": pont, "app": app}


# -- barème -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("valeurs", "attendu", "selection"),
    [  # offres de calibrage de la grille (section 3.8)
        ((5, 4, 3, 5), 88, RETENUE),
        ((4, 5, 5, 4), 88, RETENUE),
        ((5, 4, 3, 4), 85, RETENUE),
        ((4, 3, 2, 4), 68, RETENUE),
        ((1, 5, 4, 1), 48, ECARTEE),
        ((2, 1, 1, 2), 32, ECARTEE),
    ],
)
def test_calibrage_de_la_grille(valeurs: tuple[int, ...], attendu: int, selection: str) -> None:
    assert verdict(notes(*valeurs)) == (attendu, selection)


def test_fit_1_ne_passe_jamais_quel_que_soit_le_jeu_de_poids() -> None:
    meilleur = notes(1, 5, 5, 5)
    assert score(meilleur) == 64
    assert all(score(meilleur, p) < 65 for p in VARIANTES.values())
    assert verdict(meilleur) == (64, ECARTEE)


def test_limite_quand_une_seule_variante_passe() -> None:
    cas = notes(3, 2, 2, 5)  # principal (135+40+40+75)/5 = 58
    assert score(cas, VARIANTES["Apprentissage"]) == 67  # (135+30+20+150)/5
    assert verdict(cas) == (58, LIMITE)


# -- citations --------------------------------------------------------------------------------


def test_citation_ignore_casse_espaces_et_guillemets() -> None:
    texte = "We’re looking for an intern to   BUILD production ML systems."
    assert citation_presente("we're looking for an intern", texte)
    assert citation_presente("build production ml systems", texte)
    assert not citation_presente("build production LLM systems", texte)
    assert not citation_presente("BUILD", texte)  # trop courte pour prouver quoi que ce soit


# -- évaluation d'une offre -------------------------------------------------------------------


def test_offre_retenue_avec_preuves() -> None:
    entry = evaluer(note(), OFFRE, ACME)
    assert entry["statut"] == RETENUE
    assert entry["notes"] == [5, 4, 3, 5] and entry["score"] == 88
    assert entry["preuves"]["eco"] == "startup IA"
    assert entry["preuves"]["pont"] == "bureau à NYC"


def test_stage_aux_us_donne_pont_5_avec_citation_du_lieu() -> None:
    entry = evaluer(note(lieu_us=True, preuve_lieu="Mountain View, CA"), OFFRE, ACME)
    assert entry["notes"][2] == 5
    with pytest.raises(ValueError, match="preuve_lieu"):
        evaluer(note(lieu_us=True, preuve_lieu="San Francisco, CA"), OFFRE, ACME)


def test_pont_de_l_offre_ne_remonte_que_sur_preuve() -> None:
    cite = "deploy them to our robots"
    entry = evaluer(note(pont_offre=4, preuve_pont=cite), OFFRE, ACME)
    assert entry["notes"][2] == 4
    entry = evaluer(note(pont_offre=2, preuve_pont=cite), OFFRE, ACME)
    assert entry["notes"][2] == 3  # jamais en dessous de la note de l'entreprise
    with pytest.raises(ValueError, match="preuve_pont"):
        evaluer(note(pont_offre=4, preuve_pont="works with our SF office"), OFFRE, ACME)


def test_citation_inventee_refusee() -> None:
    with pytest.raises(ValueError, match="preuve_fit"):
        evaluer(note(preuve_fit="build RAG agents with LangChain"), OFFRE, ACME)


def test_apprentissage_non_precise_plafonne_a_3() -> None:
    assert evaluer(note(app=3, preuve_app="non précisé"), OFFRE, ACME)["preuves"]["app"] == (
        "non précisé"
    )
    with pytest.raises(ValueError, match="app > 3"):
        evaluer(note(app=4, preuve_app="non précisé"), OFFRE, ACME)


@pytest.mark.parametrize("champ", ["fit", "app"])
@pytest.mark.parametrize("valeur", [0, 6, 3.5, "4", True, None])
def test_notes_entieres_de_1_a_5(champ: str, valeur: Any) -> None:
    with pytest.raises(ValueError, match=champ):
        evaluer(note(**{champ: valeur}), OFFRE, ACME)


def test_offre_non_eligible_ecartee_sur_citation() -> None:
    ok = note(eligible=False, motif="fin_etudes", preuve_motif="students graduating in 2028")
    assert evaluer(ok, OFFRE, ACME) == {"statut": ECARTEE}
    with pytest.raises(ValueError, match="motif"):
        evaluer(note(eligible=False, motif="flemme", preuve_motif="x y z"), OFFRE, ACME)
    with pytest.raises(ValueError, match="preuve_motif"):
        evaluer(note(eligible=False, motif="phd", preuve_motif="PhD students only"), OFFRE, ACME)


def test_pas_un_stage_gardee_a_trancher_seulement_si_elle_passe() -> None:
    assert evaluer(note(stage=False), OFFRE, ACME)["statut"] == "a_trancher"
    hors_metier = note(stage=False, fit=1, app=1)
    assert evaluer(hors_metier, OFFRE, ACME) == {"statut": ECARTEE}


def test_champs_obligatoires() -> None:
    with pytest.raises(ValueError, match="eligible"):
        evaluer(note(eligible=None), OFFRE, ACME)
    with pytest.raises(ValueError, match="lieu_us"):
        evaluer(note(lieu_us="oui"), OFFRE, ACME)
    with pytest.raises(ValueError, match="stage"):
        evaluer(note(stage=None), OFFRE, ACME)


# -- fichier des verdicts et import -----------------------------------------------------------


def test_import_ecrit_les_verdicts_et_ne_garde_pas_la_note_des_ecartees(tmp_path: Path) -> None:
    path = tmp_path / "notes.json"
    notation = Notation.load(path)
    offres = [
        OFFRE,
        {**OFFRE, "job_id": "2"},
        {**OFFRE, "job_id": "3", "texte": "", "erreur": "HTTP 403"},
        {**OFFRE, "job_id": "4"},
    ]
    report = importer(
        notation,
        offres,
        [
            note(),
            note(job_id="2", fit=1, app=1),
            note(job_id="4", preuve_fit="texte inventé de toutes pièces"),
            note(job_id="99"),
        ],
        {"Acme": ACME},
    )
    assert report.statuts == {"retenue": 1, "ecartee": 1, "illisible": 1}
    assert len(report.erreurs) == 2  # citation inventée, offre inconnue
    notation.save()

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["ecartees"] == {"Acme": ["2"]}
    assert set(data["offres"]["Acme"]) == {"1", "3"}  # la 4 (refusée) n'est pas notée
    assert data["offres"]["Acme"]["3"]["statut"] == "illisible"

    relue = Notation.load(path)
    assert relue.est_ecartee("Acme", "2") and not relue.est_ecartee("Acme", "1")
    assert relue.est_notee("Acme", "3") and not relue.est_notee("Acme", "4")


def test_renoter_une_offre_change_son_verdict(tmp_path: Path) -> None:
    notation = Notation(tmp_path / "notes.json")
    importer(notation, [OFFRE], [note(fit=1, app=1)], {"Acme": ACME})
    assert notation.est_ecartee("Acme", "1")
    importer(notation, [OFFRE], [note()], {"Acme": ACME})
    assert not notation.est_ecartee("Acme", "1")
    assert notation.entree("Acme", "1") is not None


def test_entreprise_sans_notes_bloque_l_import() -> None:
    report = importer(Notation(None), [OFFRE], [note()], {})
    assert report.erreurs and "entreprises.yaml" in report.erreurs[0]


def test_load_entreprises_valide_les_champs(tmp_path: Path) -> None:
    path = tmp_path / "e.yaml"
    path.write_text("X: {eco: 4, eco_preuve: a, pont: 5, pont_preuve: b}\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="pont"):  # 5 est réservé au stage aux US
        load_entreprises(path)
    path.write_text("X: {eco: 4, pont: 3}\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="X"):
        load_entreprises(path)
    assert load_entreprises(tmp_path / "absent.yaml") == {}


def test_table_des_entreprises_du_depot_est_valide() -> None:
    entreprises = load_entreprises(ROOT / "notation" / "entreprises.yaml")
    assert entreprises["Amazon"].eco == 5
    assert entreprises["Sopra Steria"].eco == 1  # ESN : exemple de la note 1
    assert all(e.pont <= 3 for e in entreprises.values())  # 4 seulement sur preuve d'équipe


def test_notes_du_depot_lisibles() -> None:
    path = ROOT / "notation" / "notes.json"
    if path.exists():
        assert len(Notation.load(path)) > 0


def test_poste_de_recherche_ecarte_sur_son_intitule() -> None:
    """Décision de Matisse : aucun poste de recherche ; l'intitulé suffit comme preuve,
    même quand la page de l'offre est illisible."""
    offre = {**OFFRE, "title": "Research Intern - Reinforcement Learning, Robotics", "texte": ""}
    n = note(
        eligible=False, motif="recherche", preuve_motif="Research Intern - Reinforcement Learning"
    )
    assert evaluer(n, offre, ACME) == {"statut": ECARTEE}
