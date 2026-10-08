from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from internbot.storage import StateStore
from tests.conftest import job

T0 = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def store(tmp_path: Path, now: datetime = T0) -> StateStore:
    return StateStore.load(tmp_path / "state.json", now=lambda: now)


def test_seed_registers_without_duplicates(tmp_path: Path) -> None:
    s = store(tmp_path)
    assert not s.is_seeded("Acme")
    assert s.seed("Acme", [job("1"), job("2")]) == 2
    assert s.seed("Acme", [job("2"), job("3")]) == 1  # re-seed : n'ajoute que le nouveau
    assert s.is_seeded("Acme")
    assert s.known_ids("Acme") == {"1", "2", "3"}
    assert "notified_at" not in s.data["companies"]["Acme"]["jobs"]["1"]


def test_key_is_company_and_id(tmp_path: Path) -> None:
    s = store(tmp_path)
    s.mark_seen(job("42", company_name="A"), notified=True)
    assert s.is_known("A", "42")
    assert not s.is_known("B", "42")


def test_mark_seen_notified(tmp_path: Path) -> None:
    s = store(tmp_path)
    s.mark_seen(job("1"), notified=True)
    s.mark_seen(job("2"), notified=False)
    jobs = s.data["companies"]["Acme"]["jobs"]
    assert jobs["1"]["notified_at"] == T0.isoformat()
    assert "notified_at" not in jobs["2"]


def test_save_and_reload_roundtrip_sorted_json(tmp_path: Path) -> None:
    s = store(tmp_path)
    s.seed("Zeta", [job("b", company_name="Zeta"), job("a", company_name="Zeta")])
    s.seed("Alpha", [job("1", company_name="Alpha")])
    assert s.save()
    assert not s.save()  # rien de modifié -> pas de réécriture
    text = (tmp_path / "state.json").read_text(encoding="utf-8")
    assert text.index('"Alpha"') < text.index('"Zeta"')
    assert text.index('"a"') < text.index('"b"')
    again = store(tmp_path)
    assert again.known_ids("Zeta") == {"a", "b"}
    assert again.is_seeded("Alpha")


def test_save_is_atomic_no_temp_left(tmp_path: Path) -> None:
    s = store(tmp_path)
    s.seed("A", [job("1")])
    s.save()
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


def test_dry_run_store_without_path_never_writes(tmp_path: Path) -> None:
    s = StateStore(None)
    s.seed("A", [job("1")])
    assert s.save() is False


def test_sync_presence_removed_and_returned(tmp_path: Path) -> None:
    s = store(tmp_path)
    s.seed("Acme", [job("1"), job("2"), job("3")])
    removed, returned = s.sync_presence("Acme", ["1", "3"])
    assert (removed, returned) == (["2"], [])
    assert s.active_count("Acme") == 2
    assert s.is_known("Acme", "2")  # toujours connu : pas de re-notification s'il revient
    removed, returned = s.sync_presence("Acme", ["1", "2", "3"])
    assert (removed, returned) == ([], ["2"])


def test_prune_removed(tmp_path: Path) -> None:
    s = store(tmp_path)
    s.seed("Acme", [job("1"), job("2")])
    s.sync_presence("Acme", ["1"])
    later = StateStore(tmp_path / "x.json", s.data, now=lambda: T0 + timedelta(days=200))
    assert later.prune_removed(older_than_days=180) == 1
    assert later.known_ids("Acme") == {"1"}


def test_failures_counter(tmp_path: Path) -> None:
    s = store(tmp_path)
    assert s.record_failure("Acme", "boom") == 1
    assert s.record_failure("Acme", "boom") == 2
    assert s.failing_companies() == [("Acme", 2, "boom")]
    s.record_success("Acme")
    assert s.failing_companies() == []


def test_digest_helpers(tmp_path: Path) -> None:
    s = store(tmp_path)
    assert s.last_digest is None
    s.mark_seen(job("1", title="SWE Intern"), notified=True)
    s.set_last_digest(T0 - timedelta(days=1))
    assert s.notified_since(T0 - timedelta(days=1)) == [("Acme", "SWE Intern")]
    assert s.notified_since(T0 + timedelta(seconds=1)) == []


def test_corrupted_state_raises_clear_error(tmp_path: Path) -> None:
    (tmp_path / "state.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="corrompu"):
        store(tmp_path)


def test_unsupported_version(tmp_path: Path) -> None:
    (tmp_path / "state.json").write_text(json.dumps({"version": 99}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="Version"):
        store(tmp_path)
