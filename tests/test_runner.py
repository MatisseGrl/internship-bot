from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from internbot.config import parse_config
from internbot.errors import ProviderError
from internbot.models import Job
from internbot.notifiers.base import Notifier
from internbot.runner import Runner
from internbot.storage import StateStore
from tests.conftest import FakeProvider, job, make_http

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)


class RecordingNotifier(Notifier):
    def __init__(self, fail_ids: set[str] | None = None) -> None:
        self.sent: list[Job] = []
        self.texts: list[str] = []
        self.fail_ids = fail_ids or set()
        self.listings: list[tuple[list[Job], str]] = []
        self.listing_ok = True

    def notify(self, jobs: Sequence[Job]) -> list[Job]:
        ok = [j for j in jobs if j.job_id not in self.fail_ids]
        self.sent.extend(ok)
        return ok

    def send_text(self, text: str) -> bool:
        self.texts.append(text)
        return True

    def send_listing(self, jobs: Sequence[Job], *, subtitle: str = "") -> bool:
        self.listings.append((list(jobs), subtitle))
        return self.listing_ok


def config(*names: str, **extra: Any) -> Any:
    raw: dict[str, Any] = {
        "filters": {"keywords_any": [], "year_hint": ["2027"]},
        "companies": [{"name": n, "provider": "fake"} for n in (names or ("Acme",))],
    }
    raw.update(extra)
    return parse_config(raw)


def run(tmp_path: Path, cfg: Any, notifier: Notifier, *, now: datetime = NOW, **kw: Any) -> Any:
    state = StateStore.load(tmp_path / "state.json", now=lambda: now)
    runner = Runner(cfg, state, notifier, make_http(), now=now, **kw)
    return runner.run(cfg.companies), state


def test_first_run_seeds_silently_then_notifies_only_new(tmp_path: Path) -> None:
    cfg = config()
    FakeProvider.jobs["Acme"] = [job(str(i)) for i in range(200)]
    n = RecordingNotifier()
    report, state = run(tmp_path, cfg, n)
    assert n.sent == [] and n.texts == []  # aucun spam au premier lancement
    assert report.results[0].seeded
    assert len(state.known_ids("Acme")) == 200

    FakeProvider.jobs["Acme"].append(job("new", title="Summer 2027 Software Intern"))
    report, state = run(tmp_path, cfg, n)
    assert [j.job_id for j in n.sent] == ["new"]
    assert report.notified == 1

    report, _ = run(tmp_path, cfg, n)  # troisième run : pas de doublon
    assert len(n.sent) == 1


def test_non_matching_new_jobs_are_marked_seen_silently(tmp_path: Path) -> None:
    cfg = config()
    FakeProvider.jobs["Acme"] = []
    run(tmp_path, cfg, RecordingNotifier())
    FakeProvider.jobs["Acme"] = [
        job("a", title="Internal Audit Lead"),
        job("b", title="Summer 2026 Intern"),
        job("c", title="Data Intern"),
    ]
    n = RecordingNotifier()
    _, state = run(tmp_path, cfg, n)
    assert [j.job_id for j in n.sent] == ["c"]
    assert state.known_ids("Acme") == {"a", "b", "c"}
    assert FakeProvider.enriched == ["c"]  # enrichissement seulement pour les candidates


def test_job_marked_seen_only_after_successful_notification(tmp_path: Path) -> None:
    cfg = config()
    FakeProvider.jobs["Acme"] = []
    run(tmp_path, cfg, RecordingNotifier())
    FakeProvider.jobs["Acme"] = [job("ok"), job("ko")]

    report, state = run(tmp_path, cfg, RecordingNotifier(fail_ids={"ko"}))
    assert report.pending == 1
    assert state.is_known("Acme", "ok") and not state.is_known("Acme", "ko")

    n = RecordingNotifier()
    run(tmp_path, cfg, n)  # Telegram revenu : l'offre manquée est renvoyée
    assert [j.job_id for j in n.sent] == ["ko"]


def test_companies_are_isolated_and_errors_summarised(tmp_path: Path) -> None:
    cfg = config("Good", "Bad")
    FakeProvider.jobs["Good"] = [job("1", company_name="Good")]
    FakeProvider.errors["Bad"] = ProviderError("[fake] HTTP 500")
    report, state = run(tmp_path, cfg, RecordingNotifier())
    assert [r.ok for r in report.results] == [True, False]
    assert not report.all_failed
    assert "Bad : [fake] HTTP 500" in report.summary()
    assert state.is_seeded("Good") and not state.is_seeded("Bad")


def test_unexpected_exception_is_isolated(tmp_path: Path) -> None:
    cfg = config("Good", "Buggy")
    FakeProvider.errors["Buggy"] = ZeroDivisionError("oops")
    report, _ = run(tmp_path, cfg, RecordingNotifier())
    assert [r.ok for r in report.results] == [True, False]
    assert "ZeroDivisionError" in (report.results[1].error or "")


def test_all_failed(tmp_path: Path) -> None:
    cfg = config("A", "B")
    FakeProvider.errors["A"] = ProviderError("x")
    FakeProvider.errors["B"] = ProviderError("y")
    report, _ = run(tmp_path, cfg, RecordingNotifier())
    assert report.all_failed


def test_failure_alert_sent_once_at_threshold(tmp_path: Path) -> None:
    cfg = config("A", "B", alerts={"failure_threshold": 2})
    FakeProvider.errors["B"] = ProviderError("format cassé")
    n = RecordingNotifier()
    for _ in range(4):
        run(tmp_path, cfg, n)
    assert len(n.texts) == 1
    assert "« B » échoue depuis 2 runs" in n.texts[0]


def test_dry_run_never_writes_state_nor_notifies(tmp_path: Path) -> None:
    cfg = config()
    FakeProvider.jobs["Acme"] = [job("1")]
    n = RecordingNotifier()
    run(tmp_path, cfg, n)  # seed réel
    before = (tmp_path / "state.json").read_text(encoding="utf-8")
    FakeProvider.jobs["Acme"] = [job("2")]  # 1 disparue, 2 nouvelle
    state = StateStore.load(tmp_path / "state.json")
    state.path = None
    report = Runner(cfg, state, n, make_http(), dry_run=True).run(cfg.companies)
    assert [j.job_id for j in n.sent] == ["2"]  # affichée par le notifier (console en vrai)
    assert report.results[0].new_matches == 1
    assert (tmp_path / "state.json").read_text(encoding="utf-8") == before


def test_force_seed_registers_without_notifying(tmp_path: Path) -> None:
    cfg = config()
    FakeProvider.jobs["Acme"] = [job("1")]
    run(tmp_path, cfg, RecordingNotifier())
    FakeProvider.jobs["Acme"] = [job("1"), job("2")]
    n = RecordingNotifier()
    _, state = run(tmp_path, cfg, n, force_seed=True)
    assert n.sent == [] and state.is_known("Acme", "2")


def test_removed_jobs_detected_and_not_renotified_when_back(tmp_path: Path) -> None:
    cfg = config()
    FakeProvider.jobs["Acme"] = [job("1"), job("2")]
    run(tmp_path, cfg, RecordingNotifier())
    FakeProvider.jobs["Acme"] = [job("1")]
    report, _ = run(tmp_path, cfg, RecordingNotifier())
    assert report.results[0].removed == 1
    FakeProvider.jobs["Acme"] = [job("1"), job("2")]
    n = RecordingNotifier()
    run(tmp_path, cfg, n)
    assert n.sent == []


def test_duplicate_ids_within_a_fetch_are_deduped(tmp_path: Path) -> None:
    cfg = config()
    FakeProvider.jobs["Acme"] = []
    run(tmp_path, cfg, RecordingNotifier())
    FakeProvider.jobs["Acme"] = [job("x"), job("x")]
    n = RecordingNotifier()
    run(tmp_path, cfg, n)
    assert len(n.sent) == 1


def test_location_filter_per_company(tmp_path: Path) -> None:
    raw_companies = [
        {"name": "Acme", "provider": "fake", "filters": {"locations_include": ["France"]}}
    ]
    cfg = parse_config({"filters": {"keywords_any": []}, "companies": raw_companies})
    FakeProvider.jobs["Acme"] = []
    run(tmp_path, cfg, RecordingNotifier())
    FakeProvider.jobs["Acme"] = [job("fr", location="Paris, France"), job("us", location="NYC")]
    n = RecordingNotifier()
    run(tmp_path, cfg, n)
    assert [j.job_id for j in n.sent] == ["fr"]


def test_weekly_digest(tmp_path: Path) -> None:
    cfg = config(digest={"enabled": True, "every_days": 7})
    FakeProvider.jobs["Acme"] = []
    n = RecordingNotifier()
    run(tmp_path, cfg, n)  # initialise last_digest sans envoyer
    FakeProvider.jobs["Acme"] = [job("1", title="ML Intern")]
    run(tmp_path, cfg, n, now=NOW + timedelta(days=1))
    assert n.texts == []
    run(tmp_path, cfg, n, now=NOW + timedelta(days=8))
    assert len(n.texts) == 1
    assert "1 offre(s) notifiée(s)" in n.texts[0] and "ML Intern" in n.texts[0]


# -- liste des offres ouvertes (current.json) et --send-all ---------------------------------------


def run_snap(tmp_path: Path, cfg: Any, notifier: Notifier, **kw: Any) -> Any:
    state = StateStore.load(tmp_path / "state.json", now=lambda: NOW)
    runner = Runner(
        cfg, state, notifier, make_http(), now=NOW, snapshot_path=tmp_path / "current.json", **kw
    )
    return runner.run(cfg.companies)


def snapshot(tmp_path: Path) -> dict[str, Any]:
    import json

    data: dict[str, Any] = json.loads((tmp_path / "current.json").read_text(encoding="utf-8"))
    return data


def test_snapshot_lists_all_current_matches_including_seed(tmp_path: Path) -> None:
    cfg = config("A", "B")
    FakeProvider.jobs["A"] = [job("1", company_name="A"), job("2", "Senior Engineer", "A")]
    FakeProvider.jobs["B"] = [job("9", "Data Intern", "B")]
    run_snap(tmp_path, cfg, RecordingNotifier())  # seed : aucune notif, mais la liste existe
    snap = snapshot(tmp_path)
    assert [j["job_id"] for j in snap["companies"]["A"]["jobs"]] == ["1"]
    assert snap["companies"]["B"]["jobs"][0]["title"] == "Data Intern"
    assert snap["companies"]["B"]["jobs"][0]["url"].endswith("/9")

    FakeProvider.jobs["A"] = [job("3", "ML Intern", "A")]  # 1 disparue, 3 nouvelle
    n = RecordingNotifier()
    run_snap(tmp_path, cfg, n)
    assert [j["job_id"] for j in snapshot(tmp_path)["companies"]["A"]["jobs"]] == ["3"]
    assert [j.job_id for j in n.sent] == ["3"]


def test_snapshot_keeps_previous_list_of_failed_company(tmp_path: Path) -> None:
    cfg = config("A", "B")
    FakeProvider.jobs["A"] = [job("1", company_name="A")]
    FakeProvider.jobs["B"] = [job("9", company_name="B")]
    run_snap(tmp_path, cfg, RecordingNotifier())
    FakeProvider.errors["B"] = ProviderError("panne")
    run_snap(tmp_path, cfg, RecordingNotifier())
    assert [j["job_id"] for j in snapshot(tmp_path)["companies"]["B"]["jobs"]] == ["9"]


def test_send_all_sends_full_list_and_does_not_double_notify(tmp_path: Path) -> None:
    cfg = config()
    FakeProvider.jobs["Acme"] = [job("old")]
    run_snap(tmp_path, cfg, RecordingNotifier())
    FakeProvider.jobs["Acme"] = [job("old"), job("new", "Backend Intern")]
    n = RecordingNotifier()
    report = run_snap(tmp_path, cfg, n, send_all=True)
    (jobs, subtitle), *_ = n.listings
    assert sorted(j.job_id for j in jobs) == ["new", "old"]
    assert "mise à jour" in subtitle
    assert n.sent == []  # la nouvelle offre est déjà dans la liste
    assert report.notified == 1
    n2 = RecordingNotifier()
    run_snap(tmp_path, cfg, n2)  # et elle est bien marquée vue
    assert n2.sent == []


def test_send_all_listing_failure_falls_back_to_individual(tmp_path: Path) -> None:
    cfg = config()
    FakeProvider.jobs["Acme"] = []
    run_snap(tmp_path, cfg, RecordingNotifier())
    FakeProvider.jobs["Acme"] = [job("new")]
    n = RecordingNotifier()
    n.listing_ok = False
    run_snap(tmp_path, cfg, n, send_all=True)
    assert [j.job_id for j in n.sent] == ["new"]


def test_dry_run_does_not_write_snapshot(tmp_path: Path) -> None:
    cfg = config()
    FakeProvider.jobs["Acme"] = [job("1")]
    run_snap(tmp_path, cfg, RecordingNotifier(), dry_run=True)
    assert not (tmp_path / "current.json").exists()


def test_snapshot_resolves_multi_location_jobs_and_caches_them(tmp_path: Path) -> None:
    calls: list[str] = []

    def enrich(self: Any, company: Any, j: Job) -> Job:
        calls.append(j.job_id)
        return j.with_updates(location="China, Shanghai · China, Beijing", location_complete=True)

    FakeProvider.enrich = enrich  # type: ignore[method-assign]
    try:
        cfg = config(filters={"keywords_any": [], "locations_exclude": ["China"]})
        FakeProvider.jobs["Acme"] = [
            job("cn", location="2 Locations", location_complete=False),
            job("fr", location="Paris, France"),
        ]
        run_snap(tmp_path, cfg, RecordingNotifier())  # seed
        assert [j["job_id"] for j in snapshot(tmp_path)["companies"]["Acme"]["jobs"]] == ["fr"]
        assert calls == ["cn"]
        run_snap(tmp_path, cfg, RecordingNotifier())  # 2e run : lieu lu depuis l'état
        assert calls == ["cn"]
        assert [j["job_id"] for j in snapshot(tmp_path)["companies"]["Acme"]["jobs"]] == ["fr"]
    finally:
        del FakeProvider.enrich  # retour à l'implémentation de la classe


def test_new_job_in_china_not_notified(tmp_path: Path) -> None:
    cfg = config(filters={"keywords_any": [], "locations_exclude": ["China", "Shanghai"]})
    FakeProvider.jobs["Acme"] = []
    run_snap(tmp_path, cfg, RecordingNotifier())
    FakeProvider.jobs["Acme"] = [job("sh", location="Shanghai"), job("us", location="Seattle")]
    n = RecordingNotifier()
    run_snap(tmp_path, cfg, n)
    assert [j.job_id for j in n.sent] == ["us"]


# -- santé par entreprise (current.json › health, pour --status et /status) ----------------------


def test_health_counts_notify_review_and_failures(tmp_path: Path) -> None:
    cfg = parse_config(
        {
            "filters": {"keywords_any": ["software", "data"], "year_hint": ["2027"]},
            "companies": [
                {"name": "A", "provider": "fake"},
                {"name": "B", "provider": "fake"},
                {"name": "Off", "provider": "fake", "enabled": False},
                {"name": "G", "provider": "manual", "careers_url": "https://g", "reason": "robots"},
            ],
        }
    )
    FakeProvider.jobs["A"] = [
        job("1", "Software Engineer Intern", "A"),  # NOTIFY
        job("2", "Marketing Intern", "A"),  # REVIEW : stage, mais pas de mot-clé métier
        job("3", "Senior Software Engineer", "A"),  # REJECT
    ]
    FakeProvider.errors["B"] = ProviderError("HTTP 500")
    enabled = [c for c in cfg.companies if c.enabled]  # comme main.select_companies
    for _ in range(2):  # 2e échec d'affilée pour B
        state = StateStore.load(tmp_path / "state.json", now=lambda: NOW)
        Runner(
            cfg,
            state,
            RecordingNotifier(),
            make_http(),
            now=NOW,
            snapshot_path=tmp_path / "current.json",
        ).run(enabled)
    health = snapshot(tmp_path)["health"]
    assert health["A"] == {
        "provider": "fake",
        "status": "ok",
        "last_run": NOW.isoformat(),
        "last_success": NOW.isoformat(),
        "fetched": 3,
        "notify": 1,
        "review": 1,
        "error": None,
        "failures": 0,
    }
    assert health["B"]["status"] == "error"
    assert health["B"]["failures"] == 2
    assert "HTTP 500" in health["B"]["error"]
    assert health["B"]["last_success"] is None
    assert health["Off"]["status"] == "disabled"
    assert health["G"]["status"] == "manual"
    assert health["G"]["careers_url"] == "https://g"


def test_health_keeps_last_success_when_company_fails(tmp_path: Path) -> None:
    cfg = config("A")
    FakeProvider.jobs["A"] = [job("1", company_name="A")]
    run_snap(tmp_path, cfg, RecordingNotifier())
    FakeProvider.errors["A"] = ProviderError("panne")
    run_snap(tmp_path, cfg, RecordingNotifier())
    health = snapshot(tmp_path)["health"]["A"]
    assert health["status"] == "error"
    assert health["last_success"] == NOW.isoformat()
    assert health["fetched"] == 1  # derniers chiffres connus conservés
