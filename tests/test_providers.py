from __future__ import annotations

import builtins
import json
from typing import Any

import pytest
import responses

from internbot.errors import ProviderError, ProviderFormatError
from internbot.providers import available_providers
from internbot.providers.apple import AppleProvider
from internbot.providers.ashby import AshbyProvider
from internbot.providers.greenhouse import GreenhouseProvider
from internbot.providers.lever import LeverProvider
from internbot.providers.playwright_generic import PlaywrightGenericProvider, rows_to_jobs
from internbot.providers.smartrecruiters import SmartRecruitersProvider
from internbot.providers.workable import WorkableProvider
from tests.conftest import company, load_fixture, make_http


def test_registry_contains_all_providers() -> None:
    assert {
        "apple",
        "ashby",
        "greenhouse",
        "lever",
        "playwright",
        "smartrecruiters",
        "workable",
        "workday",
    } <= set(available_providers())


# -- Greenhouse ------------------------------------------------------------------------------------

GH_URL = "https://boards-api.greenhouse.io/v1/boards/stripe/jobs"


@responses.activate
def test_greenhouse() -> None:
    responses.get(GH_URL, json=load_fixture("greenhouse.json"))
    jobs = GreenhouseProvider(make_http()).fetch_jobs(
        company("Stripe", "greenhouse", board="stripe")
    )
    assert responses.calls[0].request.url.endswith("?content=false")
    assert len(jobs) == 3  # l'entrée sans URL est ignorée
    intern = jobs[1]
    assert intern.job_id == "8200001"
    assert intern.title == "Software Engineering Intern, Summer 2027"
    assert intern.location == "Paris, France"
    assert intern.url == "https://stripe.com/jobs/search?gh_jid=8200001"
    assert intern.posted_at == "2026-10-08"
    assert jobs[2].posted_at == "2026-10-01"  # repli sur updated_at


@responses.activate
def test_greenhouse_404_hint() -> None:
    responses.get(GH_URL, status=404, json={"status": 404})
    with pytest.raises(ProviderError, match="board inconnu"):
        GreenhouseProvider(make_http()).fetch_jobs(company("Stripe", "greenhouse", board="stripe"))


@responses.activate
def test_greenhouse_format_change() -> None:
    responses.get(GH_URL, json={"postings": []})
    with pytest.raises(ProviderFormatError):
        GreenhouseProvider(make_http()).fetch_jobs(company("Stripe", "greenhouse", board="stripe"))


# -- Lever -----------------------------------------------------------------------------------------


@responses.activate
def test_lever() -> None:
    responses.get("https://api.lever.co/v0/postings/spotify", json=load_fixture("lever.json"))
    jobs = LeverProvider(make_http()).fetch_jobs(company("Spotify", "lever", company="spotify"))
    assert "mode=json" in responses.calls[0].request.url
    assert [j.job_id for j in jobs] == [
        "2193db3f-77c5-43b8-b030-8f92c9882bf1",
        "9a8b7c6d-0000-4000-8000-000000000001",
    ]
    assert jobs[0].location == "London · Stockholm"
    assert jobs[0].posted_at == "2026-06-23"  # epoch ms -> date
    assert jobs[1].location == "Stockholm · Remote"
    assert jobs[1].url.startswith("https://jobs.lever.co/spotify/")


@responses.activate
def test_lever_eu_region_and_bad_payload() -> None:
    responses.get("https://api.eu.lever.co/v0/postings/acme", json={"error": "x"})
    with pytest.raises(ProviderFormatError):
        LeverProvider(make_http()).fetch_jobs(company("Acme", "lever", company="acme", region="eu"))


# -- Ashby -----------------------------------------------------------------------------------------


@responses.activate
def test_ashby() -> None:
    responses.get(
        "https://api.ashbyhq.com/posting-api/job-board/openai", json=load_fixture("ashby.json")
    )
    jobs = AshbyProvider(make_http()).fetch_jobs(company("OpenAI", "ashby", board="openai"))
    assert len(jobs) == 2  # l'offre isListed=false est ignorée
    research = jobs[1]
    assert research.title == "Research Engineer Intern"
    assert research.location == "London · Paris · Zurich · Remote"
    assert research.posted_at == "2026-10-07"
    assert research.url == "https://jobs.ashbyhq.com/openai/11111111-2222-3333-4444-555555555555"


# -- SmartRecruiters -------------------------------------------------------------------------------

SR_URL = "https://api.smartrecruiters.com/v1/companies/BoschGroup/postings"


@responses.activate
def test_smartrecruiters_pagination() -> None:
    responses.get(SR_URL, json=load_fixture("smartrecruiters_page1.json"))
    responses.get(SR_URL, json=load_fixture("smartrecruiters_page2.json"))
    jobs = SmartRecruitersProvider(make_http()).fetch_jobs(
        company("Bosch", "smartrecruiters", company_id="BoschGroup")
    )
    assert len(responses.calls) == 2
    assert "q=intern" in responses.calls[0].request.url
    assert "offset=100" in responses.calls[1].request.url
    assert [j.job_id for j in jobs] == ["744000154478885", "744000154470001", "744000154470002"]
    assert jobs[0].url == "https://jobs.smartrecruiters.com/BoschGroup/744000154478885"
    assert jobs[0].location == "Denham, England, United Kingdom"
    assert jobs[1].location == "Stuttgart, BW, de · Remote"
    assert jobs[0].posted_at == "2026-10-08"


# -- Workable --------------------------------------------------------------------------------------


@responses.activate
def test_workable() -> None:
    responses.get(
        "https://apply.workable.com/api/v1/widget/accounts/huggingface",
        json=load_fixture("workable.json"),
    )
    jobs = WorkableProvider(make_http()).fetch_jobs(
        company("Hugging Face", "workable", account="huggingface")
    )
    assert [j.job_id for j in jobs] == ["81B46579FE", "AB12CD34EF"]
    assert jobs[0].location == "Paris, France · Remote"
    assert jobs[1].location == "Paris, France"  # repli sur city/country
    assert jobs[1].posted_at == "2026-10-02"


# -- Playwright ------------------------------------------------------------------------------------


def test_playwright_rows_to_jobs() -> None:
    cfg = company("Maboite", "playwright", url="https://ex.com/careers/", item_selector="li")
    rows = [
        {"href": "/jobs/1", "title": "  Software\n  Intern ", "location": " Paris "},
        {"href": "/jobs/1", "title": "Software Intern", "location": "Paris"},  # doublon
        {"href": None, "title": "No link"},
        {"href": "https://other.com/2", "title": ""},
    ]
    jobs = rows_to_jobs(cfg, "https://ex.com/careers/", rows)
    assert len(jobs) == 1
    assert jobs[0].job_id == "https://ex.com/jobs/1"
    assert jobs[0].title == "Software Intern" and jobs[0].location == "Paris"


def test_playwright_missing_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("playwright"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    cfg = company("Maboite", "playwright", url="https://ex.com", item_selector="li")
    with pytest.raises(ProviderError, match="pip install"):
        PlaywrightGenericProvider(make_http()).fetch_jobs(cfg)


# -- Apple (site maison, données embarquées dans le HTML) -------------------------------------------

APPLE_URL = "https://jobs.apple.com/en-us/search"


def apple_html(data: Any) -> str:
    """Reproduit la page d'Apple : JSON encodé dans un littéral de chaîne JS."""
    data = json.dumps(data)
    return (
        "<html><head><script>window.__staticRouterHydrationData = "
        f"JSON.parse({json.dumps(data)});</script></head><body></body></html>"
    )


@responses.activate
def test_apple_paginates_and_parses() -> None:
    responses.get(APPLE_URL, body=apple_html(load_fixture("apple_page1.json")))
    responses.get(APPLE_URL, body=apple_html(load_fixture("apple_page2.json")))
    jobs = AppleProvider(make_http()).fetch_jobs(company("Apple", "apple"))

    assert len(responses.calls) == 2  # 4 offres annoncées, 2 par page
    assert "team=internships-STDNT-INTRN" in responses.calls[0].request.url
    assert "page=2" in responses.calls[1].request.url
    assert [j.job_id for j in jobs] == ["200687446-1731", "200682900-3715", "200620855-2114"]
    first = jobs[0]
    assert first.title == "Internship - Cellular Protocol"
    assert first.location == "Munich, Germany"
    assert first.url == (
        "https://jobs.apple.com/en-us/details/200687446-1731/internship-cellular-protocol"
    )
    assert first.posted_at == "2026-10-08"
    assert jobs[1].location == "Shanghai, China"  # exclu ensuite par le filtre de lieu
    assert jobs[2].location == "United States"  # lieu = pays : pas de répétition


@responses.activate
def test_apple_custom_team_and_stops_on_empty_page() -> None:
    empty = {"loaderData": {"search": {"totalRecords": 50, "searchResults": []}}}
    responses.get(APPLE_URL, body=apple_html(empty))
    jobs = AppleProvider(make_http()).fetch_jobs(company("Apple", "apple", team="students-STDNT"))
    assert jobs == []
    assert len(responses.calls) == 1
    assert "team=students-STDNT" in responses.calls[0].request.url


@responses.activate
def test_apple_format_change_is_reported() -> None:
    responses.get(APPLE_URL, body="<html>nouveau site</html>")
    with pytest.raises(ProviderFormatError, match="introuvables"):
        AppleProvider(make_http()).fetch_jobs(company("Apple", "apple"))


@responses.activate
def test_apple_http_error() -> None:
    responses.get(APPLE_URL, status=403, body="Forbidden")
    with pytest.raises(ProviderError, match=r"\[apple\] Apple"):
        AppleProvider(make_http(max_retries=0)).fetch_jobs(company("Apple", "apple"))
