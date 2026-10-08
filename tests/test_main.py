from __future__ import annotations

from pathlib import Path

import pytest

from internbot.errors import ProviderError
from internbot.main import EXIT_CONFIG, EXIT_FAILURE, EXIT_OK, main
from tests.conftest import FakeProvider, job

CONFIG = """
notifier: {type: console}
filters: {keywords_any: []}
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
