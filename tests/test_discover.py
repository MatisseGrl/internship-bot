from __future__ import annotations

import json

import pytest
import responses
import yaml

from internbot.discover import (
    Discoverer,
    parse_apply_url,
    parse_entry,
    render_report,
    run_discovery,
    slug_candidates,
)
from internbot.main import main
from tests.conftest import make_http

# Avec `responses`, toute URL non enregistrée lève une erreur de connexion : la sonde
# correspondante est simplement considérée comme « introuvable ».


def disc() -> Discoverer:
    return Discoverer(make_http(max_retries=0))


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Anthropic", ["anthropic"]),
        ("Scale AI", ["scaleai", "scale-ai", "scale"]),
        ("Epic Games", ["epicgames", "epic-games", "epic"]),
        ("Palo Alto Networks", ["paloaltonetworks", "palo-alto-networks", "paloalto", "palo-alto"]),
        ("Société Générale", ["societegenerale", "societe-generale"]),
        ("", []),
    ],
)
def test_slug_candidates(name: str, expected: list[str]) -> None:
    assert slug_candidates(name) == expected


def test_parse_entry() -> None:
    assert parse_entry("Anthropic") == ("Anthropic", None)
    assert parse_entry("Slack=https://x.wd1.myworkdayjobs.com/S") == (
        "Slack",
        "https://x.wd1.myworkdayjobs.com/S",
    )
    assert parse_entry("https://jobs.lever.co/spotify") == ("", "https://jobs.lever.co/spotify")


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://salesforce.wd12.myworkdayjobs.com/en-US/External_Career_Site/job/X_JR1",
            ("workday", {"tenant": "salesforce", "wd": "wd12", "site": "External_Career_Site"}),
        ),
        (
            "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite",
            ("workday", {"tenant": "nvidia", "wd": "wd5", "site": "NVIDIAExternalCareerSite"}),
        ),
        (
            "https://wd3.myworkdaysite.com/en-US/recruiting/acme/Acme_Careers/job/1",
            ("workday", {"tenant": "acme", "wd": "wd3", "site": "Acme_Careers"}),
        ),
        ("https://job-boards.greenhouse.io/anthropic/jobs/123", ("greenhouse", {"board": "anthropic"})),
        ("https://boards.greenhouse.io/embed/job_board?for=stripe", ("greenhouse", {"board": "stripe"})),
        ("https://jobs.lever.co/spotify/abc", ("lever", {"company": "spotify"})),
        ("https://jobs.eu.lever.co/acme/abc", ("lever", {"company": "acme", "region": "eu"})),
        ("https://jobs.ashbyhq.com/openai/abc", ("ashby", {"board": "openai"})),
        ("https://jobs.smartrecruiters.com/BoschGroup/7440", ("smartrecruiters", {"company_id": "BoschGroup"})),
        ("https://apply.workable.com/huggingface/j/ABC", ("workable", {"account": "huggingface"})),
        ("https://careers.google.com/jobs/results/", None),
    ],
)  # fmt: skip
def test_parse_apply_url(url: str, expected: object) -> None:
    assert parse_apply_url(url) == expected


GH = "https://boards-api.greenhouse.io/v1/boards/{}/jobs"


@responses.activate
def test_name_found_on_greenhouse_with_org_check() -> None:
    responses.get(GH.format("anthropic"), json={"jobs": [{"company_name": "Anthropic"}] * 3})
    f = disc().discover("Anthropic")
    assert f.found and f.probe is not None
    assert f.probe.provider == "greenhouse" and f.probe.options == {"board": "anthropic"}
    assert f.probe.jobs == 3
    assert f.notes == []
    assert f.to_config() == {"name": "Anthropic", "provider": "greenhouse", "board": "anthropic"}


@responses.activate
def test_short_slug_with_other_org_is_flagged() -> None:
    responses.get(GH.format("epic"), json={"jobs": [{"company_name": "Epic Systems"}]})
    f = disc().discover("Epic Games")
    assert f.found
    assert any("à vérifier" in n and "Epic Systems" in n for n in f.notes)


@responses.activate
def test_exact_slug_preferred_and_empty_board_reported() -> None:
    responses.get("https://api.lever.co/v0/postings/acme", json=[])
    responses.get("https://api.ashbyhq.com/posting-api/job-board/acme", json={"jobs": [{}] * 5})
    f = disc().discover("Acme")
    assert f.probe is not None and f.probe.provider == "ashby"
    assert any("lever « acme » existe mais est vide" in n for n in f.notes)


@responses.activate
def test_lever_eu_fallback() -> None:
    responses.get("https://api.lever.co/v0/postings/acme", status=404)
    responses.get("https://api.eu.lever.co/v0/postings/acme", json=[{"id": 1}])
    f = disc().discover("Acme")
    assert f.probe is not None
    assert f.probe.options == {"company": "acme", "region": "eu"}


@responses.activate
def test_workday_wd_then_site_search() -> None:
    base = "https://acme.{wd}.myworkdayjobs.com/wday/cxs/acme/{site}/jobs"
    responses.post(base.format(wd="wd1", site="internbot_probe_site"), status=422, json={})
    responses.post(base.format(wd="wd5", site="internbot_probe_site"), status=404, json={})
    responses.post(base.format(wd="wd5", site="External"), status=404, json={})
    responses.post(base.format(wd="wd5", site="External_Career_Site"), status=404, json={})
    responses.post(base.format(wd="wd5", site="ExternalCareerSite"), status=404, json={})
    responses.post(base.format(wd="wd5", site="Careers"), json={"total": 42, "jobPostings": []})
    f = disc().discover("Acme")
    assert f.probe is not None
    assert f.to_config() == {
        "name": "Acme", "provider": "workday", "tenant": "acme", "wd": "wd5", "site": "Careers",
    }  # fmt: skip
    assert f.probe.jobs == 42
    bodies = [json.loads(c.request.body) for c in responses.calls if c.request.method == "POST"]
    assert all(b["limit"] == 1 for b in bodies)


@responses.activate
def test_url_entry_verified() -> None:
    url = "https://salesforce.wd12.myworkdayjobs.com/wday/cxs/salesforce/Slack/jobs"
    responses.post(url, json={"total": 12, "jobPostings": []})
    f = disc().discover("Slack=https://salesforce.wd12.myworkdayjobs.com/en-US/Slack")
    assert f.name == "Slack"
    assert f.to_config()["site"] == "Slack"


@responses.activate
def test_url_entry_wrong_identifier() -> None:
    f = disc().discover("https://jobs.ashbyhq.com/nope")
    assert not f.found and "ne répond pas" in f.notes[0]
    assert f.name == "Nope"


def test_unsupported_url() -> None:
    f = disc().discover("Google=https://careers.google.com/jobs/results/")
    assert not f.found and "non reconnue" in f.notes[0]


@responses.activate
def test_not_found_anywhere() -> None:
    f = disc().discover("Zzqq Corp")
    assert not f.found and "Nom=URL" in f.notes[-1]


@responses.activate
def test_report_is_valid_yaml_and_loadable_config(tmp_path: object) -> None:
    responses.get(GH.format("anthropic"), json={"jobs": [{"company_name": "Anthropic"}]})
    findings = run_discovery(["# commentaire", "", "Anthropic", "Zzqq"], make_http(max_retries=0))
    report = render_report(findings)
    data = yaml.safe_load(report)
    assert data == [{"name": "Anthropic", "provider": "greenhouse", "board": "anthropic"}]
    assert "# - Zzqq" in report


@responses.activate
def test_cli_discover(
    tmp_path: pytest.TempPathFactory,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("internbot.main.HttpClient", lambda **kw: make_http(max_retries=0))
    responses.get(GH.format("anthropic"), json={"jobs": [{"company_name": "Anthropic"}]})
    out = tmp_path / "found.yaml"  # type: ignore[operator]
    assert main(["--discover", "Anthropic", "--discover-out", str(out), "-c", "missing.yaml"]) == 0
    assert "board: anthropic" in out.read_text(encoding="utf-8")
    assert "board: anthropic" in capsys.readouterr().out
    assert main(["--discover", "Zzqq", "-c", "missing.yaml"]) == 1
