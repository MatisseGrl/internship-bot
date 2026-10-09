from __future__ import annotations

import json
from datetime import date

import pytest
import responses

from internbot.errors import ProviderError, ProviderFormatError
from internbot.providers.workday import WorkdayProvider, extract_job_id, parse_posted_on
from tests.conftest import company, load_fixture, make_http

BASE = "https://salesforce.wd12.myworkdayjobs.com"
LIST_URL = f"{BASE}/wday/cxs/salesforce/External_Career_Site/jobs"
SF = company("Salesforce", "workday", tenant="salesforce", wd="wd12", site="External_Career_Site")


@responses.activate
def test_paginates_with_total_from_first_page_only() -> None:
    # Particularité Workday : la page 2 renvoie total=0 ; on doit quand même la lire.
    responses.post(LIST_URL, json=load_fixture("workday_page1.json"))
    responses.post(LIST_URL, json=load_fixture("workday_page2.json"))
    jobs = WorkdayProvider(make_http()).fetch_jobs(SF)

    assert len(jobs) == 23
    assert len(responses.calls) == 2
    bodies = [json.loads(c.request.body) for c in responses.calls]
    assert [b["offset"] for b in bodies] == [0, 20]
    assert bodies[0] == {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "intern"}
    req = responses.calls[0].request
    assert req.headers["Content-Type"] == "application/json"
    assert req.headers["Accept"] == "application/json"

    swe = jobs[0]
    assert swe.job_id == "JR340771"
    assert swe.company == "Salesforce"
    assert swe.source == "workday"
    assert swe.url == (
        f"{BASE}/External_Career_Site/job/California---San-Francisco/"
        "Summer-2027-Intern---Software-Engineer_JR340771-1"
    )
    assert swe.location == "8 Locations" and not swe.location_complete
    assert jobs[1].location_complete


@responses.activate
def test_plusieurs_recherches_sans_doublons() -> None:
    intern = {
        "title": "Software Intern",
        "externalPath": "/job/Paris/Software-Intern_JR123456",
        "bulletFields": ["JR123456"],
        "locationsText": "Paris",
    }
    stage = {
        "title": "Stage Data",
        "externalPath": "/job/Paris/Stage-Data_JR123457",
        "bulletFields": ["JR123457"],
        "locationsText": "Paris",
    }
    responses.post(LIST_URL, json={"total": 1, "jobPostings": [intern]})
    responses.post(LIST_URL, json={"total": 2, "jobPostings": [intern, stage]})
    cfg = company(
        "Salesforce",
        "workday",
        tenant="salesforce",
        wd="wd12",
        site="External_Career_Site",
        search_texts=["intern", "stage"],
    )
    jobs = WorkdayProvider(make_http()).fetch_jobs(cfg)
    assert [job.job_id for job in jobs] == ["JR123456", "JR123457"]
    assert [json.loads(call.request.body)["searchText"] for call in responses.calls] == [
        "intern",
        "stage",
    ]


@responses.activate
def test_stops_on_empty_page_and_respects_max_pages() -> None:
    page = load_fixture("workday_page1.json")
    page["total"] = 10_000
    responses.post(LIST_URL, json=page)
    cfg = company(
        "Salesforce",
        "workday",
        tenant="salesforce",
        wd="wd12",
        site="External_Career_Site",
        max_pages=3,
        search_text="stage",
    )
    jobs = WorkdayProvider(make_http()).fetch_jobs(cfg)
    assert len(responses.calls) == 3
    assert len(jobs) == 60
    assert json.loads(responses.calls[0].request.body)["searchText"] == "stage"

    responses.reset()
    responses.post(LIST_URL, json={"total": 0, "jobPostings": []})
    assert WorkdayProvider(make_http()).fetch_jobs(SF) == []


@responses.activate
def test_wrong_wd_gives_helpful_error() -> None:
    responses.post(LIST_URL, status=422, json={"errorCode": "HTTP_422", "httpStatus": 422})
    with pytest.raises(ProviderError, match="tenant/wd/site"):
        WorkdayProvider(make_http()).fetch_jobs(SF)


@responses.activate
def test_format_change_detected() -> None:
    responses.post(LIST_URL, json={"total": 3, "postings": []})
    with pytest.raises(ProviderFormatError, match="jobPostings"):
        WorkdayProvider(make_http()).fetch_jobs(SF)


@responses.activate
def test_all_items_unreadable_is_format_error() -> None:
    responses.post(LIST_URL, json={"total": 2, "jobPostings": [{"name": "x"}, {"foo": 1}]})
    with pytest.raises(ProviderFormatError, match="format modifié"):
        WorkdayProvider(make_http()).fetch_jobs(SF)


@responses.activate
def test_enrich_fetches_full_locations_and_date() -> None:
    responses.post(LIST_URL, json=load_fixture("workday_page2.json"))
    provider = WorkdayProvider(make_http())
    jobs = provider.fetch_jobs(SF)
    swe = next(j for j in jobs if j.job_id == "JR340771")
    detail_url = f"{BASE}/wday/cxs/salesforce/External_Career_Site{swe.extra['external_path']}"
    responses.get(detail_url, json=load_fixture("workday_detail.json"))

    enriched = provider.enrich(SF, swe)
    assert enriched.location.startswith("California - San Francisco · California - Palo Alto")
    assert "Indiana - Indianapolis" in enriched.location
    assert enriched.location_complete
    assert enriched.posted_at == "2026-08-31"


@responses.activate
def test_enrich_failure_keeps_job_and_respects_cap() -> None:
    responses.post(LIST_URL, json=load_fixture("workday_page2.json"))
    cfg = company(
        "Salesforce",
        "workday",
        tenant="salesforce",
        wd="wd12",
        site="External_Career_Site",
        max_details=1,
    )
    provider = WorkdayProvider(make_http(max_retries=0))
    jobs = provider.fetch_jobs(cfg)
    responses.get(
        f"{BASE}/wday/cxs/salesforce/External_Career_Site{jobs[0].extra['external_path']}",
        status=500,
    )
    assert provider.enrich(cfg, jobs[0]) == jobs[0]
    calls = len(responses.calls)
    assert provider.enrich(cfg, jobs[2]) == jobs[2]  # plafond atteint : aucune requête
    assert len(responses.calls) == calls


@pytest.mark.parametrize(
    ("posting", "expected"),
    [
        ({"bulletFields": ["JR340771"], "externalPath": "/job/x/Foo_JR340771-1"}, "JR340771"),
        ({"bulletFields": ["Paris", "R-12345"], "externalPath": "/job/x/Foo_R-12345"}, "R-12345"),
        ({"bulletFields": [], "externalPath": "/job/x/Software-Intern_JR355555-2"}, "JR355555"),
        ({"bulletFields": [], "externalPath": "/job/x/Software-Intern_2024-0042"}, "2024-0042"),
        ({"externalPath": "/job/x/No-Id-Here"}, "/job/x/No-Id-Here"),
    ],
)
def test_extract_job_id(posting: dict[str, object], expected: str) -> None:
    assert extract_job_id(posting) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Posted Today", "2026-10-08"),
        ("Posted Yesterday", "2026-10-07"),
        ("Posted 3 Days Ago", "2026-10-05"),
        ("Posted 30+ Days Ago", "Posted 30+ Days Ago"),
        (None, None),
    ],
)
def test_parse_posted_on(raw: str | None, expected: str | None) -> None:
    assert parse_posted_on(raw, today=date(2026, 10, 8)) == expected
