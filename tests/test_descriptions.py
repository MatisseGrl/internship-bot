from __future__ import annotations

import json

import pytest
import responses

from internbot.descriptions import (
    DescriptionError,
    DescriptionFetcher,
    html_to_text,
    jobposting_text,
)
from tests.conftest import company, job, make_http

LONG = "You will build and ship production machine learning systems with your mentor. " * 8


def fetcher(*companies: object) -> DescriptionFetcher:
    return DescriptionFetcher(make_http(max_retries=0), {c.name: c for c in companies})  # type: ignore[attr-defined]


def test_html_to_text_garde_les_paragraphes_et_ignore_scripts_et_menus() -> None:
    page = (
        "<html><head><title>x</title><script>var a = 1;</script></head><body>"
        "<nav>Home Jobs</nav><h1>ML Intern</h1><p>Build &amp; ship<br>models</p>"
        "<ul><li>Python</li><li>PyTorch</li></ul><footer>© Acme</footer></body></html>"
    )
    text = html_to_text(page, skip_chrome=True)
    assert text.splitlines() == ["ML Intern", "Build & ship", "models", "- Python", "- PyTorch"]
    assert "Home" in html_to_text(page)  # menus gardés hors page complète


def test_jobposting_text_lit_le_json_ld() -> None:
    ld = {
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "Organization", "name": "Acme"},
            {
                "@type": "JobPosting",
                "title": "ML Intern",
                "description": "&lt;p&gt;Train models&lt;/p&gt;",
                "employmentType": ["INTERN"],
                "jobLocation": {"address": {"addressLocality": "Paris", "addressCountry": "FR"}},
            },
        ],
    }
    page = f'<script type="application/ld+json">{json.dumps(ld)}</script>'
    assert jobposting_text(page) == (
        "Intitulé : ML Intern\nLieu : Paris, FR\nType de contrat : INTERN\nTrain models"
    )
    assert jobposting_text('<script type="application/ld+json">{oops</script>') is None


@responses.activate
def test_greenhouse_via_api_meme_pour_une_vitrine() -> None:
    responses.get(
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs/123",
        json={"title": "ML Intern", "location": {"name": "NYC"}, "content": f"&lt;p&gt;{LONG}"},
    )
    acme = company(provider="greenhouse", board="acme")
    j = job("123").with_updates(url="https://acme.com/careers?gh_jid=123")
    description = fetcher(acme).fetch(j)
    assert description.source == "api greenhouse"
    assert description.text.startswith("Intitulé : ML Intern\nLieu : NYC\nYou will build")


@responses.activate
def test_page_sans_json_ld_lue_en_texte_visible() -> None:
    responses.get("https://example.com/jobs/1", body=f"<main><p>{LONG}</p></main>")
    description = fetcher(company(provider="workday")).fetch(job("1"))
    assert description.source == "page" and "production machine learning" in description.text


@responses.activate
def test_page_protegee_ou_vide_illisible() -> None:
    responses.get("https://example.com/jobs/1", body="<html><script>challenge()</script></html>")
    responses.get("https://example.com/jobs/2", status=403)
    f = fetcher(company(provider="sitemap"))
    with pytest.raises(DescriptionError, match="trop court"):
        f.fetch(job("1"))
    with pytest.raises(DescriptionError, match="403"):
        f.fetch(job("2"))
    with pytest.raises(DescriptionError, match="absente de la config"):
        f.fetch(job("3", company_name="Inconnue"))


@responses.activate
def test_smartrecruiters_via_api() -> None:
    responses.get(
        "https://api.smartrecruiters.com/v1/companies/Acme1/postings/42",
        json={
            "name": "Data Intern",
            "location": {"city": "Paris", "country": "fr"},
            "jobAd": {"sections": {"jobDescription": {"title": "Missions", "text": LONG}}},
        },
    )
    description = fetcher(company(provider="smartrecruiters", company_id="Acme1")).fetch(job("42"))
    assert description.text.splitlines()[:3] == [
        "Intitulé : Data Intern",
        "Lieu : Paris, fr",
        "Missions",
    ]


@responses.activate
def test_page_utf8_sans_charset_bien_decodee() -> None:
    corps = f"<main><p>Élève ingénieur : {LONG}</p></main>".encode()
    responses.get("https://example.com/jobs/1", body=corps, content_type="text/html")
    description = fetcher(company(provider="workday")).fetch(job("1"))
    assert description.text.startswith("Élève ingénieur")
