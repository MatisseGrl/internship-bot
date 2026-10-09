"""Providers des sites maison et plateformes secondaires : custom_json, eightfold, oracle_hcm,
avature, manual. Aucun accès réseau : fixtures + `responses`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import responses
from responses import matchers

from internbot.errors import ProviderError, ProviderFormatError
from internbot.providers import available_providers
from internbot.providers.avature import AvatureProvider, parse_results
from internbot.providers.base import epoch_date, get_path
from internbot.providers.custom_json import (
    CustomJsonProvider,
    parse_date,
    render_field,
    substitute,
)
from internbot.providers.eightfold import EightfoldProvider
from internbot.providers.manual import ManualProvider
from internbot.providers.oracle_hcm import OracleHcmProvider
from tests.conftest import FIXTURES, company, load_fixture, make_http


def _html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_registry_contains_new_providers() -> None:
    assert {"avature", "custom_json", "eightfold", "manual", "oracle_hcm"} <= set(
        available_providers()
    )


# -- utilitaires ---------------------------------------------------------------------------------


def test_get_path() -> None:
    data = {"a": {"b": [{"c": 1}, {"c": 2}]}}
    assert get_path(data, "a.b.1.c") == 2
    assert get_path(data, "a.b.-1.c") == 2
    assert get_path(data, "a.x", "def") == "def"
    assert get_path(data, "a.b.5.c") is None
    assert get_path([1, 2], ".") == [1, 2]


def test_epoch_date_seconds_and_ms() -> None:
    assert epoch_date(1787097600) == "2026-08-19"
    assert epoch_date(1787097600000) == "2026-08-19"
    assert epoch_date(0) is None
    assert epoch_date("2026-10-01T10:00:00Z") == "2026-10-01"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("October  8, 2026", "2026-10-08"),
        ("Oct 8, 2026", "2026-10-08"),
        ("2026-09-24 03:33 PM", "2026-09-24"),
        ("Fri, 18 Jul 2025 00:00:00 +0000", "2025-07-18"),
        (1789603200, "2026-09-17"),
        (None, None),
    ],
)
def test_parse_date(raw: object, expected: str | None) -> None:
    assert parse_date(raw) == expected


def test_substitute_placeholders() -> None:
    variables = {"offset": 40, "page": 3, "page0": 2, "limit": 20}
    assert substitute({"from": "{offset}", "q": "x", "n": ["{limit}"]}, variables) == {
        "from": 40,
        "q": "x",
        "n": [20],
    }
    assert substitute("https://x/?p={page}&o={offset}", variables) == "https://x/?p=3&o=40"


def test_render_field_template_and_list() -> None:
    item = {"path": "/jobs/1", "city": "Paris", "country": "FR"}
    assert render_field(item, "https://x.com{path}") == "https://x.com/jobs/1"
    assert render_field(item, ["city", "country"]) == ["Paris", "FR"]
    with pytest.raises(ValueError):
        render_field(item, "https://x.com{missing}")


# -- custom_json ---------------------------------------------------------------------------------

AMAZON_URL = "https://www.amazon.jobs/en/search.json"


def _amazon(**overrides: object) -> object:
    opts: dict[str, object] = {
        "url": AMAZON_URL,
        "params": {"base_query": "intern", "result_limit": "{limit}", "offset": "{offset}"},
        "items_path": "jobs",
        "total_path": "hits",
        "page_size": 2,
        "fields": {
            "id": "id_icims",
            "title": "title",
            "url": "https://www.amazon.jobs{job_path}",
            "location": "normalized_location",
            "date": "posted_date",
        },
    }
    opts.update(overrides)
    return company("Amazon", "custom_json", **opts)


@responses.activate
def test_custom_json_paginated_get() -> None:
    responses.get(
        AMAZON_URL,
        match=[
            matchers.query_param_matcher(
                {"base_query": "intern", "result_limit": "2", "offset": "0"}
            )
        ],
        json=load_fixture("custom_json_page1.json"),
    )
    responses.get(
        AMAZON_URL,
        match=[
            matchers.query_param_matcher(
                {"base_query": "intern", "result_limit": "2", "offset": "2"}
            )
        ],
        json=load_fixture("custom_json_page2.json"),
    )
    jobs = CustomJsonProvider(make_http()).fetch_jobs(_amazon())  # type: ignore[arg-type]
    assert len(responses.calls) == 2  # total (3) atteint : pas de 3e page
    assert [j.job_id for j in jobs] == ["10573264", "10573999", "10574000"]  # sans id : ignorée
    first = jobs[0]
    assert first.title == "Software Development Engineer Intern - 2027"
    assert first.url == "https://www.amazon.jobs/en/jobs/10573264/sde-intern-2027"
    assert first.location == "Dublin, IRL"
    assert first.posted_at == "2026-10-08"
    assert first.source == "custom_json"


@responses.activate
def test_custom_json_post_body_and_root_list() -> None:
    url = "https://api.example.com/search"
    responses.post(
        url,
        match=[matchers.json_params_matcher({"size": 50, "from": 0, "q": "intern"})],
        json=[
            {
                "ref": "A1",
                "name": "Data Intern",
                "link": "https://example.com/A1",
                "where": ["Paris", "Lyon"],
            }
        ],
    )
    acme = company(
        "Acme",
        "custom_json",
        url=url,
        method="POST",
        body={"size": "{limit}", "from": "{offset}", "q": "intern"},
        page_size=50,
        items_path=".",
        fields={"id": "ref", "title": "name", "url": "link", "location": "where"},
    )
    jobs = CustomJsonProvider(make_http()).fetch_jobs(acme)
    assert [(j.job_id, j.location) for j in jobs] == [("A1", "Paris · Lyon")]


@responses.activate
def test_custom_json_format_change() -> None:
    responses.get(AMAZON_URL, json={"results": []})
    with pytest.raises(ProviderFormatError, match="'jobs' n'est pas une liste"):
        CustomJsonProvider(make_http()).fetch_jobs(_amazon())  # type: ignore[arg-type]


@responses.activate
def test_custom_json_http_error_is_isolated() -> None:
    responses.get(AMAZON_URL, status=403, body="blocked")
    with pytest.raises(ProviderError, match="HTTP 403"):
        CustomJsonProvider(make_http()).fetch_jobs(_amazon())  # type: ignore[arg-type]


def test_custom_json_requires_id_title_url_fields() -> None:
    with pytest.raises(ProviderError, match=r"fields\.url"):
        CustomJsonProvider(make_http()).fetch_jobs(
            _amazon(fields={"id": "id", "title": "title"})  # type: ignore[arg-type]
        )


# -- eightfold -----------------------------------------------------------------------------------


@responses.activate
def test_eightfold_v2() -> None:
    responses.get(
        "https://explore.jobs.netflix.net/api/apply/v2/jobs",
        match=[
            matchers.query_param_matcher(
                {"domain": "netflix.com", "query": "intern", "start": "0", "num": "10"}
            )
        ],
        json=load_fixture("eightfold_v2.json"),
    )
    jobs = EightfoldProvider(make_http()).fetch_jobs(
        company("Netflix", "eightfold", host="explore.jobs.netflix.net", domain="netflix.com")
    )
    assert [j.job_id for j in jobs] == ["JR42220", "JR42300"]
    assert jobs[0].url == "https://explore.jobs.netflix.net/careers/job/790317917022"
    assert jobs[0].location == (
        "Los Gatos,California,United States of America · Remote, United States"
    )
    assert jobs[0].posted_at == "2026-08-19"


@responses.activate
def test_eightfold_pcsx() -> None:
    responses.get(
        "https://careers.qualcomm.com/api/pcsx/search",
        match=[
            matchers.query_param_matcher(
                {"domain": "qualcomm.com", "query": "intern", "start": "0", "location": ""}
            )
        ],
        json=load_fixture("eightfold_pcsx.json"),
    )
    jobs = EightfoldProvider(make_http()).fetch_jobs(
        company(
            "Qualcomm", "eightfold", host="careers.qualcomm.com", domain="qualcomm.com", api="pcsx"
        )
    )
    assert len(jobs) == 1
    assert jobs[0].job_id == "3096484"
    assert jobs[0].url == "https://careers.qualcomm.com/careers/job/446721064018"
    assert jobs[0].location == "Markham, Ontario, Canada"


@responses.activate
def test_eightfold_wrong_api_hint() -> None:
    responses.get(
        "https://careers.qualcomm.com/api/apply/v2/jobs",
        status=403,
        json={"message": "Not authorized for PCSX"},
    )
    with pytest.raises(ProviderError, match="autre valeur de `api`"):
        EightfoldProvider(make_http()).fetch_jobs(
            company("Qualcomm", "eightfold", host="careers.qualcomm.com", domain="qualcomm.com")
        )


# -- oracle_hcm ----------------------------------------------------------------------------------


@responses.activate
def test_oracle_hcm() -> None:
    base = "https://eeho.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
    responses.get(base, json=load_fixture("oracle_hcm.json"))
    jobs = OracleHcmProvider(make_http()).fetch_jobs(
        company("Oracle", "oracle_hcm", host="eeho.fa.us2.oraclecloud.com", site="CX_45001")
    )
    url = responses.calls[0].request.url
    assert "finder=findReqs;siteNumber=CX_45001,keyword=intern,limit=25,offset=0" in url
    assert len(responses.calls) == 1  # TotalJobsCount atteint
    assert [j.job_id for j in jobs] == ["334396", "334345"]
    assert jobs[0].location == "Redwood City, CA, United States · Seattle, WA, United States"
    assert jobs[0].url == (
        "https://eeho.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_45001/job/334396"
    )
    assert jobs[0].posted_at == "2026-10-02"


@responses.activate
def test_oracle_hcm_format_change() -> None:
    responses.get(
        "https://jpmc.fa.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions",
        json={"items": [{"jobs": []}]},
    )
    with pytest.raises(ProviderFormatError, match="requisitionList"):
        OracleHcmProvider(make_http()).fetch_jobs(
            company("JPMorgan", "oracle_hcm", host="jpmc.fa.oraclecloud.com", site="CX_1001")
        )


# -- avature -------------------------------------------------------------------------------------

EA_SEARCH = "https://jobs.ea.com/en_US/careers/SearchJobs/"


def test_avature_parse_results() -> None:
    rows, total = parse_results(_html("avature_page1.html"))
    assert total == 3
    assert rows == [
        {
            "href": "https://jobs.ea.com/en_US/careers/JobDetail/Software-Engineer-Intern/216251",
            "title": "Software Engineer Intern - SUMMER 2027",
            "location": "Orlando, United States of America",
        },
        {
            "href": "https://jobs.ea.com/en_US/careers/JobDetail/Gameplay-Engineer-Intern/216245",
            "title": "Gameplay Engineer Intern & Tools",
            "location": "Los Angeles - Chatsworth, United States of America",
        },
    ]


def test_avature_variantes_siemens_et_totalenergies() -> None:
    siemens, total_siemens = parse_results(_html("avature_siemens.html"))
    totalenergies, total_totalenergies = parse_results(_html("avature_totalenergies.html"))
    assert total_siemens is None  # « 999+ » est une borne, pas un total exact.
    assert [row["title"] for row in siemens] == [
        "Strategic Student Program: Mendix Development Intern",
        "Software Engineer Intern",
    ]
    assert siemens[0]["location"] == "St. Louis, Missouri, United States of America"
    assert total_totalenergies == 1
    assert totalenergies[0]["location"] == "France"
    assert totalenergies[0]["href"].endswith("/84412")


def test_avature_aucun_resultat_valide() -> None:
    rows, total = parse_results(
        '<div class="list-controls__text__legend" aria-label="0 results"></div>'
    )
    assert rows == []
    assert total == 0


@responses.activate
def test_avature_paginated() -> None:
    for offset, page in ((0, "avature_page1.html"), (2, "avature_page2.html")):
        responses.get(
            EA_SEARCH,
            match=[
                matchers.query_param_matcher(
                    {"search": "intern", "jobRecordsPerPage": "2", "jobOffset": str(offset)}
                )
            ],
            body=_html(page),
        )
    jobs = AvatureProvider(make_http()).fetch_jobs(
        company("EA", "avature", base_url="https://jobs.ea.com/en_US/careers/", page_size=2)
    )
    assert [j.job_id for j in jobs] == ["216251", "216245", "216222"]
    assert jobs[2].location == ""  # lieu absent : inconnu, jamais rejeté


@responses.activate
def test_avature_pagination_taille_imposee_par_portail() -> None:
    for offset, page in ((0, "avature_page1.html"), (2, "avature_page2.html")):
        responses.get(
            EA_SEARCH,
            match=[
                matchers.query_param_matcher(
                    {"jobRecordsPerPage": "20", "jobOffset": str(offset), "search": "intern"}
                )
            ],
            body=_html(page),
        )
    jobs = AvatureProvider(make_http()).fetch_jobs(
        company("EA", "avature", base_url="https://jobs.ea.com/en_US/careers/")
    )
    assert [job.job_id for job in jobs] == ["216251", "216245", "216222"]


@responses.activate
def test_avature_siemens_pagination_dossiers() -> None:
    url = "https://jobs.siemens.com/en_US/externaljobs/SearchJobs/"
    for offset, page in (
        (0, _html("avature_siemens.html")),
        (
            2,
            '<article class="article article--result"><h3><a '
            'href="https://jobs.siemens.com/en_US/externaljobs/JobDetail/520463">'
            "Data Intern</a></h3></article>",
        ),
    ):
        responses.get(
            url,
            match=[
                matchers.query_param_matcher(
                    {
                        "folderRecordsPerPage": "6",
                        "folderOffset": str(offset),
                        "search": "intern",
                    }
                )
            ],
            body=page,
        )
    jobs = AvatureProvider(make_http()).fetch_jobs(
        company(
            "Siemens",
            "avature",
            base_url="https://jobs.siemens.com/en_US/externaljobs",
            query="intern",
            page_size=6,
            page_size_param="folderRecordsPerPage",
            offset_param="folderOffset",
            max_pages=2,
        )
    )
    assert [job.job_id for job in jobs] == ["520461", "520462", "520463"]


@responses.activate
def test_avature_detecte_une_pagination_bloquee() -> None:
    for offset in (0, 2):
        responses.get(
            EA_SEARCH,
            match=[
                matchers.query_param_matcher(
                    {"jobRecordsPerPage": "2", "jobOffset": str(offset), "search": "intern"}
                )
            ],
            body=_html("avature_page1.html"),
        )
    with pytest.raises(ProviderFormatError, match="pagination bloquée"):
        AvatureProvider(make_http()).fetch_jobs(
            company("EA", "avature", base_url="https://jobs.ea.com/en_US/careers", page_size=2)
        )


@responses.activate
def test_avature_plusieurs_recherches_sans_doublons() -> None:
    def listing(ids: list[int]) -> str:
        articles = "".join(
            f'<article class="article article--result"><h3><a '
            f'href="https://jobs.ea.com/en_US/careers/JobDetail/Offre/{job_id}">'
            f"Stage {job_id}</a></h3></article>"
            for job_id in ids
        )
        return (
            f'<div class="list-controls__text__legend">1-{len(ids)} of {len(ids)} results</div>'
            + articles
        )

    for query, ids in (("internship", [216251]), ("stage", [216251, 216222])):
        responses.get(
            EA_SEARCH,
            match=[
                matchers.query_param_matcher(
                    {"jobRecordsPerPage": "20", "jobOffset": "0", "search": query}
                )
            ],
            body=listing(ids),
        )
    jobs = AvatureProvider(make_http()).fetch_jobs(
        company(
            "EA",
            "avature",
            base_url="https://jobs.ea.com/en_US/careers",
            queries=["internship", "stage"],
        )
    )
    assert [job.job_id for job in jobs] == ["216251", "216222"]


@responses.activate
def test_avature_unexpected_page() -> None:
    responses.get(EA_SEARCH, body="<html><body>Maintenance</body></html>")
    with pytest.raises(ProviderFormatError, match="format modifié"):
        AvatureProvider(make_http()).fetch_jobs(
            company("EA", "avature", base_url="https://jobs.ea.com/en_US/careers")
        )


# -- manual --------------------------------------------------------------------------------------


@responses.activate
def test_manual_never_fetches() -> None:
    google = company(
        "Google", "manual", careers_url="https://careers.google.com", reason="robots.txt"
    )
    assert ManualProvider.automated is False
    with pytest.raises(ProviderError, match="suivie à la main"):
        ManualProvider(make_http()).fetch_jobs(google)
    assert len(responses.calls) == 0


def test_fixtures_are_valid_json() -> None:
    for path in Path(FIXTURES).glob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))


# -- sitemap -------------------------------------------------------------------------------------


@responses.activate
def test_sitemap_index_and_talentbrew_urls() -> None:
    from internbot.providers.sitemap import SitemapProvider, slug_to_text

    responses.get("https://jobs.example.com/sitemap.xml", body=_html("sitemap_index.xml"))
    responses.get("https://jobs.example.com/sitemap1.xml", body=_html("sitemap_jobs.xml"))
    jobs = SitemapProvider(make_http()).fetch_jobs(
        company("Intuit", "sitemap", url="https://jobs.example.com/sitemap.xml")
    )
    assert [(j.job_id, j.title, j.location) for j in jobs] == [
        ("99856180864", "Summer 2027 Software Engineering Intern Full Stack", "Mountain View"),
        ("101643259568", "Intern", "Petah Tikva"),
        ("101711266304", "Staff Financial Analyst", "San Diego"),
    ]
    assert jobs[1].url == "https://jobs.example.com/job/petah-tikva/intern/27595/101643259568"
    assert slug_to_text("c%2B%2B-developer-intern_2027") == "C++ Developer Intern 2027"


@responses.activate
def test_sitemap_not_xml() -> None:
    from internbot.providers.sitemap import SitemapProvider

    responses.get("https://jobs.example.com/sitemap.xml", body="<html>maintenance</html>")
    with pytest.raises(ProviderFormatError, match="pas un sitemap"):
        SitemapProvider(make_http()).fetch_jobs(
            company("Intuit", "sitemap", url="https://jobs.example.com/sitemap.xml")
        )
