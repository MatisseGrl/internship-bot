"""Contrat de lecture de l'API Exalead de Dassault Systèmes (3ds.com/apisearch)."""

from __future__ import annotations

import pytest
import responses

from internbot.errors import ProviderFormatError
from internbot.providers.exalead import ExaleadProvider
from tests.conftest import company, load_fixture, make_http

API = "https://www.3ds.com/apisearch/card_search_api"


def _company(**opts: object):
    return company("Dassault Systèmes", "exalead", api_url=API, **opts)


@responses.activate
def test_fetch_real_page() -> None:
    responses.get(API, json=load_fixture("exalead_page1.json"))
    jobs = ExaleadProvider(make_http()).fetch_jobs(_company())
    assert len(jobs) == 3
    first = jobs[0]
    assert (first.job_id, first.title) == ("550025", "AI Engineer")
    assert first.url == "https://www.3ds.com/careers/jobs/ai-engineer-550025"
    assert first.location == "United States, MA, Waltham"
    assert first.posted_at == "2026-10-10"
    assert first.source == "exalead"


@responses.activate
def test_paginates_until_total() -> None:
    page = load_fixture("exalead_page1.json")
    page["nhits"] = 4
    second = {"nhits": 4, "hits": page["hits"][:1]}
    second["hits"] = [{"metas": [{"name": "card_id", "value": "999"}, {"name": "content_title", "value": "Intern"}, {"name": "content_cta_1_url", "value": "https://www.3ds.com/careers/jobs/intern-999"}]}]
    responses.get(API, json=page)
    responses.get(API, json=second)
    jobs = ExaleadProvider(make_http()).fetch_jobs(_company(page_size=3))
    assert [j.job_id for j in jobs][-1] == "999"
    assert len(jobs) == 4
    assert "b=3" in responses.calls[1].request.url


@responses.activate
def test_format_change_is_reported() -> None:
    responses.get(API, json={"unexpected": True})
    with pytest.raises(ProviderFormatError):
        ExaleadProvider(make_http()).fetch_jobs(_company())
