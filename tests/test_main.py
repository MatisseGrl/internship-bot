from __future__ import annotations

import json
from pathlib import Path

import pytest
import responses

from internbot.errors import ProviderError
from internbot.main import EXIT_CONFIG, EXIT_FAILURE, EXIT_OK, main
from tests.conftest import FakeProvider, job

CONFIG = """
notifier: {type: console}
filters: {year_hint: []}
companies:
  - {name: Acme, provider: fake}
  - {name: Other, provider: fake, enabled: false}
"""


@pytest.fixture
def cfg_path(tmp_path: Path) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(CONFIG, encoding="utf-8")
    return p


def test_invalid_config_exit_code(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("companies:\n  - {name: X, provider: nope}\n", encoding="utf-8")
    assert main(["run", "-c", str(p)]) == EXIT_CONFIG
    assert main(["run", "-c", str(tmp_path / "missing.yaml")]) == EXIT_CONFIG


def test_list_companies(cfg_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--list-companies", "-c", str(cfg_path)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "Acme" in out and "[désactivée]" in out


def test_run_then_new_job(
    cfg_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state = tmp_path / "s" / "state.json"
    FakeProvider.jobs["Acme"] = [job("1")]
    assert main(["run", "-c", str(cfg_path), "--state", str(state)]) == EXIT_OK
    assert state.exists()
    assert "🆕" not in capsys.readouterr().out  # seed silencieux
    FakeProvider.jobs["Acme"] = [job("1"), job("2", title="Backend Intern")]
    assert main(["-c", str(cfg_path), "--state", str(state)]) == EXIT_OK
    assert "Backend Intern" in capsys.readouterr().out


def test_dry_run_does_not_create_state(cfg_path: Path, tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    FakeProvider.jobs["Acme"] = [job("1")]
    assert main(["run", "--dry-run", "-c", str(cfg_path), "--state", str(state)]) == EXIT_OK
    assert not state.exists()


def test_all_sources_failed_exit_code(cfg_path: Path, tmp_path: Path) -> None:
    FakeProvider.errors["Acme"] = ProviderError("down")
    assert main(["-c", str(cfg_path), "--state", str(tmp_path / "s.json")]) == EXIT_FAILURE


def test_company_option(cfg_path: Path, tmp_path: Path) -> None:
    FakeProvider.errors["Acme"] = ProviderError("down")
    # --company force une entreprise désactivée ; Acme (en échec) n'est pas traitée
    assert (
        main(["-c", str(cfg_path), "--state", str(tmp_path / "s.json"), "--company", "other"])
        == EXIT_OK
    )
    assert main(["-c", str(cfg_path), "--company", "Unknown"]) == EXIT_CONFIG


def test_telegram_without_secrets_is_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.chdir(tmp_path)  # pas de .env
    p = tmp_path / "c.yaml"
    p.write_text("companies:\n  - {name: Acme, provider: fake}\n", encoding="utf-8")
    assert main(["--test-notify", "-c", str(p)]) == EXIT_CONFIG


MANUAL_CONFIG = """
notifier: {type: console}
filters: {keywords_any: []}
companies:
  - {name: Acme, provider: fake}
  - {name: Broken, provider: fake}
  - name: Google
    provider: manual
    careers_url: https://www.google.com/about/careers/applications/jobs/results
    reason: robots.txt interdit la page de résultats
"""


def test_manual_companies_are_never_fetched_and_status_lists_them(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(MANUAL_CONFIG, encoding="utf-8")
    state = tmp_path / "state.json"
    FakeProvider.jobs["Acme"] = [job("1"), job("2", title="Marketing Coordinator")]
    FakeProvider.errors["Broken"] = ProviderError("HTTP 503")
    assert main(["run", "-c", str(cfg), "--state", str(state)]) == EXIT_OK
    capsys.readouterr()

    assert main(["--status", "-c", str(cfg), "--state", str(state)]) == EXIT_OK
    out = capsys.readouterr().out
    lines = {line.split()[0]: line for line in out.splitlines() if line[:1].isalpha()}
    assert " ok " in lines["Acme"] and lines["Acme"].split()[-2:] == ["1", "0"]
    assert " error " in lines["Broken"] and "1 échec(s) d'affilée" in lines["Broken"]
    assert " manual " in lines["Google"] and "robots.txt" in lines["Google"]
    assert out.splitlines()[1].startswith("Broken")  # erreurs en tête
    assert "3 entreprise(s) : 1 error, 1 ok, 1 manual" in out

    # --company sur une entreprise manuelle : message clair, pas de requête
    assert main(["-c", str(cfg), "--state", str(state), "--company", "google"]) == EXIT_CONFIG


def test_status_without_any_run(
    cfg_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--status", "-c", str(cfg_path), "--state", str(tmp_path / "s.json")]) == EXIT_OK
    out = capsys.readouterr().out
    assert "pending" in out and "disabled" in out and "jamais" in out


@responses.activate
def test_a_noter_puis_importer_notes(cfg_path: Path, tmp_path: Path) -> None:
    """Export du texte des offres ouvertes, notation, import : l'offre écartée disparaît."""
    state = tmp_path / "s" / "state.json"
    FakeProvider.jobs["Acme"] = [job("1", title="ML Intern"), job("2", title="Data Intern")]
    assert main(["run", "-c", str(cfg_path), "--state", str(state)]) == EXIT_OK
    texte = "You will train and evaluate ranking models with a dedicated mentor. " * 10
    responses.get("https://example.com/jobs/1", body=f"<p>{texte}</p>")
    responses.get("https://example.com/jobs/2", status=403)

    work = tmp_path / "travail"
    assert main(["--a-noter", str(work), "-c", str(cfg_path), "--state", str(state)]) == EXIT_OK
    rows = [json.loads(line) for line in (work / "offres.jsonl").read_text("utf-8").splitlines()]
    assert {r["job_id"]: bool(r.get("erreur")) for r in rows} == {"1": False, "2": True}
    # Relancé : rien n'est retéléchargé.
    assert main(["--a-noter", str(work), "-c", str(cfg_path), "--state", str(state)]) == EXIT_OK
    assert len(responses.calls) == 2

    (tmp_path / "notation").mkdir()
    (tmp_path / "notation" / "entreprises.yaml").write_text(
        "Acme: {eco: 2, eco_preuve: inconnue, pont: 1, pont_preuve: aucun lien US}\n",
        encoding="utf-8",
    )
    note = {
        "company": "Acme", "job_id": "1", "eligible": True, "stage": True, "lieu_us": False,
        "fit": 2, "preuve_fit": "train and evaluate ranking models",
        "app": 2, "preuve_app": "with a dedicated mentor", "conditions": "non précisé",
    }  # fmt: skip
    (work / "notes-1.jsonl").write_text(json.dumps(note) + "\n", encoding="utf-8")
    assert main(["--importer-notes", str(work), "-c", str(cfg_path)]) == EXIT_OK
    notes = json.loads((tmp_path / "notation" / "notes.json").read_text("utf-8"))
    assert notes["ecartees"] == {"Acme": ["1"]}
    assert notes["offres"]["Acme"]["2"]["statut"] == "illisible"

    # Passage suivant : l'offre écartée n'est plus dans la liste /offres, l'illisible reste.
    assert main(["run", "-c", str(cfg_path), "--state", str(state)]) == EXIT_OK
    current = json.loads(state.with_name("current.json").read_text("utf-8"))
    assert [j["job_id"] for j in current["companies"]["Acme"]["jobs"]] == ["2"]

    # Une citation inventée fait échouer l'import (code 1) sans rien casser.
    note["preuve_fit"] = "build LLM agents"
    (work / "notes-1.jsonl").write_text(json.dumps(note) + "\n", encoding="utf-8")
    assert main(["--importer-notes", str(work), "-c", str(cfg_path)]) == EXIT_FAILURE
    assert json.loads((tmp_path / "notation" / "notes.json").read_text("utf-8")) == notes


def test_importer_notes_en_simulation_n_ecrit_rien(
    cfg_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    work = tmp_path / "travail"
    work.mkdir()
    texte = "You will build backend services for our payments platform every day."
    offre = {
        "company": "Acme",
        "job_id": "1",
        "title": "SWE Intern",
        "location": "Paris",
        "texte": texte,
    }
    (work / "offres.jsonl").write_text(json.dumps(offre) + "\n", encoding="utf-8")
    note = {
        "company": "Acme", "job_id": "1", "eligible": True, "stage": True, "lieu_us": False,
        "fit": 4, "preuve_fit": "build backend services", "app": 3, "preuve_app": "non précisé",
    }  # fmt: skip
    (work / "notes-a.jsonl").write_text(json.dumps(note) + "\n", encoding="utf-8")
    (tmp_path / "notation").mkdir()
    (tmp_path / "notation" / "entreprises.yaml").write_text(
        "Acme: {eco: 4, eco_preuve: x, pont: 3, pont_preuve: y}\n", encoding="utf-8"
    )
    args = ["--importer-notes", str(work), "--simulation", "-c", str(cfg_path)]
    assert main(args) == EXIT_OK
    assert "retenue      73  Acme — SWE Intern" in capsys.readouterr().out
    assert not (tmp_path / "notation" / "notes.json").exists()
