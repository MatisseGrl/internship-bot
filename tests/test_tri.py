from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from internbot import runner as runner_mod
from internbot.descriptions import DescriptionError
from internbot.models import Job
from internbot.notation import Notation
from internbot.runner import Runner
from internbot.storage import StateStore
from internbot.tri import ModeleTri, _caracteres, _mots
from tests.conftest import FakeProvider, job, make_http
from tests.test_runner import RecordingNotifier, config

NOW = datetime(2026, 11, 2, 12, tzinfo=UTC)
MODELE = Path(__file__).resolve().parents[1] / "notation" / "tri_tfidf.json.gz"

# Scores calculés par scikit-learn (TfidfVectorizer + LogisticRegression.decision_function)
# sur le modèle livré, au moment où il a été figé.
CAS_SKLEARN = [
    ("Software Engineer Intern - Summer 2027",
     "Build backend services in Python and Go. You will ship code to production with a mentor.",
     4.110399834119162),
    ("Stage Chargé de Communication F/H",
     "Rédaction de contenus, réseaux sociaux, événements internes. Stage de fin d'études de "
     "6 mois dès janvier 2027.",
     -4.392040609752576),
    ("Machine Learning Intern",
     "Train and evaluate deep learning models (PyTorch). Currently pursuing a Master's degree "
     "in Computer Science.",
     2.6396980745561827),
    ("Werkstudent (m/w/d) Logistik", "Unterstützung im Lager, 15-20 Stunden pro Woche.",
     -3.321918362705489),
]  # fmt: skip


@pytest.mark.parametrize(("titre", "texte", "attendu"), CAS_SKLEARN)
def test_modele_livre_reproduit_scikit_learn(titre: str, texte: str, attendu: float) -> None:
    modele = ModeleTri.load(MODELE)
    assert modele.score(titre, texte) == pytest.approx(attendu, abs=1e-3)


def test_modele_livre_garde_un_stage_logiciel_et_ecarte_la_communication() -> None:
    modele = ModeleTri.load(MODELE)
    assert modele.garder(modele.score(*CAS_SKLEARN[0][:2]))
    assert not modele.garder(modele.score(*CAS_SKLEARN[1][:2]))


def test_ngrammes_comme_scikit_learn() -> None:
    assert list(_mots("go to c++ prod")) == ["go", "to", "prod", "go to", "to prod"]
    # char_wb : mot bordé d'espaces ; arrêt dès que n atteint la longueur du mot bordé
    # (valeurs relevées sur scikit-learn 1.9)
    assert list(_caracteres("ab")) == [" ab", "ab ", " ab "]
    assert list(_caracteres("a  b")) == [" a ", " b "]
    assert list(_caracteres("abc")) == [" ab", "abc", "bc ", " abc", "abc ", " abc "]


# -- intégration au runner ---------------------------------------------------------------------


def offre(job_id: str) -> Job:
    return job(job_id, title="Data Intern 2027")  # « data » : notify, sans mot du modèle jouet


def jouet() -> ModeleTri:
    """« software » fait garder l'offre, « marketing » la fait masquer (seuil 0)."""
    return ModeleTri(
        version="jouet",
        seuil=0.0,
        biais=0.0,
        texte_max=8000,
        mots={"software": [1.0, 10.0], "marketing": [1.0, -10.0]},
        caracteres={},
    )


class Textes:
    def __init__(self, textes: dict[str, str]) -> None:
        self.textes = textes
        self.lus: list[str] = []

    def __call__(self, job: Job) -> str:
        self.lus.append(job.job_id)
        if job.job_id not in self.textes:
            raise DescriptionError("page protégée")
        return self.textes[job.job_id]


def lancer(
    tmp_path: Path,
    textes: Callable[[Job], str],
    n: RecordingNotifier | None = None,
    **kw: Any,
) -> tuple[RecordingNotifier, StateStore]:
    n = n or RecordingNotifier()
    state = StateStore.load(tmp_path / "state.json", now=lambda: NOW)
    if kw.get("dry_run"):
        state.path = None
    cfg = config()
    Runner(
        cfg,
        state,
        n,
        make_http(),
        now=NOW,
        snapshot_path=tmp_path / "current.json",
        tri=jouet(),
        texte=textes,
        **kw,
    ).run(cfg.companies)
    return n, state


def affichees(tmp_path: Path) -> list[str]:
    import json

    snap = json.loads((tmp_path / "current.json").read_text(encoding="utf-8"))
    return sorted(j["job_id"] for j in snap["companies"]["Acme"]["jobs"])


def test_nouvelle_offre_sous_le_seuil_ni_notifiee_ni_affichee(tmp_path: Path) -> None:
    FakeProvider.jobs["Acme"] = []
    lancer(tmp_path, Textes({}))  # seed
    FakeProvider.jobs["Acme"] = [offre("bon"), offre("mauvais")]
    textes = Textes({"bon": "software backend", "mauvais": "marketing events"})
    n, state = lancer(tmp_path, textes)
    assert [j.job_id for j in n.sent] == ["bon"]
    assert affichees(tmp_path) == ["bon"]
    assert state.is_known("Acme", "mauvais")  # marquée vue : pas renotifiée plus tard
    assert state.cached_tri("Acme", "mauvais", "jouet") == (True, -10.0)
    assert state.cached_tri("Acme", "bon", "jouet") == (True, 10.0)

    n, _ = lancer(tmp_path, textes)  # run suivant : score en cache, aucune relecture
    assert n.sent == [] and sorted(textes.lus) == ["bon", "mauvais"]


def test_offre_notee_avec_la_grille_jamais_masquee(tmp_path: Path) -> None:
    FakeProvider.jobs["Acme"] = [offre("notee")]
    notation = Notation(None)
    notation.gardee("Acme", "notee", {"statut": "retenue", "score": 80})
    textes = Textes({"notee": "marketing"})
    lancer(tmp_path, textes, notation=notation)
    assert affichees(tmp_path) == ["notee"] and textes.lus == []


def test_texte_illisible_offre_gardee(tmp_path: Path) -> None:
    FakeProvider.jobs["Acme"] = []
    lancer(tmp_path, Textes({}))
    FakeProvider.jobs["Acme"] = [offre("ibm")]
    n, state = lancer(tmp_path, Textes({}))
    assert [j.job_id for j in n.sent] == ["ibm"]
    assert state.cached_tri("Acme", "ibm", "jouet") == (True, None)  # pas de nouvel essai


def test_offres_anciennes_triees_au_fil_des_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner_mod, "TRI_ANCIENNES_PAR_RUN", 1)
    FakeProvider.jobs["Acme"] = [offre("a"), offre("b")]
    textes = Textes({"a": "marketing", "b": "marketing"})
    lancer(tmp_path, textes)  # seed : une seule offre triée, l'autre reste visible
    assert len(affichees(tmp_path)) == 1
    lancer(tmp_path, textes)
    assert affichees(tmp_path) == []
    assert sorted(textes.lus) == ["a", "b"]


def test_dry_run_ne_garde_pas_les_scores(tmp_path: Path) -> None:
    FakeProvider.jobs["Acme"] = []
    lancer(tmp_path, Textes({}))
    FakeProvider.jobs["Acme"] = [offre("x")]
    _, state = lancer(tmp_path, Textes({"x": "marketing"}), dry_run=True)
    assert state.cached_tri("Acme", "x", "jouet") == (False, None)


def test_sans_modele_rien_n_est_masque(tmp_path: Path) -> None:
    FakeProvider.jobs["Acme"] = [offre("x")]
    state = StateStore.load(tmp_path / "state.json", now=lambda: NOW)
    cfg = config()
    Runner(
        cfg, state, RecordingNotifier(), make_http(), now=NOW,
        snapshot_path=tmp_path / "current.json",
    ).run(cfg.companies)  # fmt: skip
    assert affichees(tmp_path) == ["x"]
