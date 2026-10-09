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
        self.digests: list[tuple[str, list[Job]]] = []
        self.digest_ok = True

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

    def send_digest(self, title: str, jobs: Sequence[Job]) -> bool:
        self.digests.append((title, list(jobs)))
        return self.digest_ok


def config(*names: str, **extra: Any) -> Any:
    raw: dict[str, Any] = {
        "filters": {"year_hint": ["2027"]},
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
    raw_companies = [{"name": "Acme", "provider": "fake", "filters": {"regions": ["europe"]}}]
    cfg = parse_config({"companies": raw_companies})
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
        cfg = config()
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
    cfg = config()
    FakeProvider.jobs["Acme"] = []
    run_snap(tmp_path, cfg, RecordingNotifier())
    FakeProvider.jobs["Acme"] = [job("sh", location="Shanghai"), job("us", location="Seattle")]
    n = RecordingNotifier()
    run_snap(tmp_path, cfg, n)
    assert [j.job_id for j in n.sent] == ["us"]


# -- filtre v3 : seaux notify / review / drop ------------------------------------------------------

MORNING = datetime(2026, 10, 9, 6, 30, tzinfo=UTC)  # 8 h 30 à Paris (heure d'été : UTC+2)


def seeded(tmp_path: Path, cfg: Any, **kw: Any) -> None:
    FakeProvider.jobs["Acme"] = []
    run(tmp_path, cfg, RecordingNotifier(), **kw)


def test_review_job_goes_to_daily_digest_not_immediate_alert(tmp_path: Path) -> None:
    cfg = config()
    seeded(tmp_path, cfg, now=MORNING)
    FakeProvider.jobs["Acme"] = [job("r", title="Hardware Machine Learning Research Intern")]
    n = RecordingNotifier()
    report, state = run(tmp_path, cfg, n, now=MORNING)  # 8 h 30 : pas encore de résumé
    assert n.sent == [] and n.digests == []
    assert report.results[0].new_reviews == 1 and "1 à vérifier" in report.summary()
    assert state.is_known("Acme", "r")  # vue : jamais renotifiée
    assert [j.job_id for j in state.review_queue()] == ["r"]

    n = RecordingNotifier()
    run(tmp_path, cfg, n, now=MORNING + timedelta(hours=1))  # 9 h 30 : premier passage après 9 h
    (title, jobs), *_ = n.digests
    assert "À vérifier : 1" in title
    assert [(j.job_id, j.priority) for j in jobs] == [("r", True)]
    assert "hardware + IA" in jobs[0].reason

    n = RecordingNotifier()
    FakeProvider.jobs["Acme"].append(job("r2", title="Machine Learning Intern", location=""))
    _, state = run(tmp_path, cfg, n, now=MORNING + timedelta(hours=5))
    assert n.digests == []  # un seul résumé par jour : r2 attend demain
    assert [j.job_id for j in state.review_queue()] == ["r2"]
    n = RecordingNotifier()
    run(tmp_path, cfg, n, now=MORNING + timedelta(days=1, hours=1))
    assert [j.job_id for j in n.digests[0][1]] == ["r2"]


def test_review_digest_kept_when_sending_fails(tmp_path: Path) -> None:
    cfg = config()
    seeded(tmp_path, cfg)
    FakeProvider.jobs["Acme"] = [job("r", title="AI Solution Architect Intern")]
    n = RecordingNotifier()
    n.digest_ok = False
    _, state = run(tmp_path, cfg, n)
    assert len(n.digests) == 1 and [j.job_id for j in state.review_queue()] == ["r"]
    n = RecordingNotifier()
    _, state = run(tmp_path, cfg, n)  # même jour, mais pas encore envoyé : on réessaie
    assert len(n.digests) == 1 and state.review_queue() == []


def test_drop_reason_logged_in_verbose(tmp_path: Path, caplog: Any) -> None:
    cfg = config()
    seeded(tmp_path, cfg)
    FakeProvider.jobs["Acme"] = [job("hw", title="Validation Engineer Intern")]
    n = RecordingNotifier()
    with caplog.at_level("DEBUG", logger="internbot.runner"):
        _, state = run(tmp_path, cfg, n)
    assert n.sent == [] and state.review_queue() == [] and state.is_known("Acme", "hw")
    assert "ignorée « Validation Engineer Intern » — hardware (validation engineer)" in caplog.text


def test_ai_jobs_flagged_and_sent_first(tmp_path: Path) -> None:
    cfg = config()
    seeded(tmp_path, cfg)
    FakeProvider.jobs["Acme"] = [job("swe"), job("ml", title="Machine Learning Engineer Intern")]
    n = RecordingNotifier()
    run(tmp_path, cfg, n)
    assert [(j.job_id, j.priority) for j in n.sent] == [("ml", True), ("swe", False)]


def test_snapshot_has_notify_and_review_with_verdict_but_no_drop(tmp_path: Path) -> None:
    cfg = config()
    FakeProvider.jobs["Acme"] = [
        job("swe"),
        job("ml", title="Machine Learning Intern", location="Multiple Locations"),
        job("hw", title="Silicon Hardware Engineering - Intern", location="Hillsboro, OR"),
    ]
    run_snap(tmp_path, cfg, RecordingNotifier())
    jobs = {j["job_id"]: j for j in snapshot(tmp_path)["companies"]["Acme"]["jobs"]}
    assert set(jobs) == {"swe", "ml"}
    assert jobs["swe"]["status"] == "notify" and not jobs["swe"]["priority"]
    assert jobs["ml"]["status"] == "review" and jobs["ml"]["priority"]
    assert jobs["ml"]["reason"] == "IA (machine learning) / lieu non précisé"


# -- passage au filtre v3 : récap unique des offres que l'ancien filtre cachait --------------------


def old_filter_state(
    tmp_path: Path, *, shown: list[str], hidden: list[str], notified: list[str]
) -> None:
    """État et current.json tels que les laissait l'ancien filtre (pas de filter_version)."""
    import json

    ts = "2026-10-01T00:00:00+00:00"
    jobs: dict[str, Any] = {i: {"title": "x", "first_seen": ts} for i in shown + hidden}
    jobs.update({i: {"title": "x", "first_seen": ts, "notified_at": ts} for i in notified})
    acme = {"seeded_at": ts, "consecutive_failures": 0, "last_error": None, "jobs": jobs}
    state = {"version": 1, "meta": {}, "companies": {"Acme": acme}}
    (tmp_path / "state.json").write_text(json.dumps(state), encoding="utf-8")
    listed = [{"job_id": i, "title": "x", "location": "", "url": "u"} for i in shown + notified]
    current = {"version": 1, "updated_at": ts, "companies": {"Acme": {"jobs": listed}}}
    (tmp_path / "current.json").write_text(json.dumps(current), encoding="utf-8")


def test_v3_migration_sends_one_recap_of_previously_hidden_jobs(tmp_path: Path) -> None:
    old_filter_state(tmp_path, shown=["shown"], hidden=["hidden", "hw"], notified=["done"])
    FakeProvider.jobs["Acme"] = [
        job("shown"),  # déjà visible dans /offres : pas de récap
        job("hidden", title="Data Analyst Intern"),  # cachée avant, notify maintenant : récap
        job("hw", title="Validation Engineer Intern"),  # toujours écartée
        job("done"),  # déjà notifiée
        job("new", title="Backend Intern"),  # vraiment nouvelle : alerte normale
    ]
    cfg = config()
    n = RecordingNotifier()
    report = run_snap(tmp_path, cfg, n)
    assert [j.job_id for j in n.sent] == ["new"]
    (title, jobs), *_ = n.digests
    assert "1 offre(s) ouverte(s) que l'ancien filtre cachait" in title
    assert [j.job_id for j in jobs] == ["hidden"]
    assert report.notified == 1

    n = RecordingNotifier()
    run_snap(tmp_path, cfg, n)  # une seule fois
    assert n.sent == [] and n.digests == []
    state = StateStore.load(tmp_path / "state.json")
    assert state.filter_version == 3 and state.was_notified("Acme", "hidden")


def test_v3_migration_recap_retried_until_sent(tmp_path: Path) -> None:
    old_filter_state(tmp_path, shown=[], hidden=["hidden"], notified=[])
    FakeProvider.jobs["Acme"] = [job("hidden")]
    n = RecordingNotifier()
    n.digest_ok = False
    run_snap(tmp_path, config(), n)
    n = RecordingNotifier()
    run_snap(tmp_path, config(), n)  # current.json est maintenant celui du v3 : récap gardé
    assert [j.job_id for j in n.digests[0][1]] == ["hidden"]
    n = RecordingNotifier()
    run_snap(tmp_path, config(), n)
    assert n.digests == []


def test_v3_migration_waits_for_a_full_run(tmp_path: Path) -> None:
    old_filter_state(tmp_path, shown=[], hidden=["hidden"], notified=[])
    FakeProvider.jobs["Acme"] = [job("hidden")]
    cfg = config("Acme", "Other")
    state = StateStore.load(tmp_path / "state.json", now=lambda: NOW)
    n = RecordingNotifier()
    Runner(cfg, state, n, make_http(), now=NOW, snapshot_path=tmp_path / "current.json").run(
        cfg.companies[:1]
    )  # --company Acme
    assert n.digests == []
    assert StateStore.load(tmp_path / "state.json").filter_version == 1


def test_v3_migration_without_previous_list_sends_nothing(tmp_path: Path) -> None:
    old_filter_state(tmp_path, shown=[], hidden=["hidden"], notified=[])
    (tmp_path / "current.json").unlink()
    FakeProvider.jobs["Acme"] = [job("hidden")]
    n = RecordingNotifier()
    run_snap(tmp_path, config(), n)
    assert n.digests == [] and n.sent == []


def test_v3_migration_dry_run_previews_without_writing(tmp_path: Path) -> None:
    old_filter_state(tmp_path, shown=[], hidden=["hidden"], notified=[])
    before = (tmp_path / "state.json").read_text(encoding="utf-8")
    FakeProvider.jobs["Acme"] = [job("hidden")]
    n = RecordingNotifier()
    state = StateStore.load(tmp_path / "state.json")
    state.path = None
    snap = tmp_path / "current.json"
    Runner(config(), state, n, make_http(), now=NOW, dry_run=True, snapshot_path=snap).run(
        config().companies
    )
    assert [j.job_id for j in n.digests[0][1]] == ["hidden"]
    assert (tmp_path / "state.json").read_text(encoding="utf-8") == before
