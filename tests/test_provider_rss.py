"""Contrat de lecture du flux RSS public Teamtailor."""

from __future__ import annotations

import pytest
import responses

from internbot.errors import ProviderFormatError
from internbot.providers.rss import RssProvider
from tests.conftest import FIXTURES, company, make_http

URL = "https://careers.payfit.com/jobs.rss"


@responses.activate
def test_teamtailor_feed_uses_stable_guids_and_locations() -> None:
    responses.get(URL, body=(FIXTURES / "teamtailor_jobs.rss").read_text(encoding="utf-8"))
    jobs = RssProvider(make_http()).fetch_jobs(company("PayFit", "rss", url=URL))
    assert len(jobs) == 2
    assert jobs[0].job_id == "stable-guid-8525347"
    assert jobs[0].posted_at == "2026-10-09"
    assert jobs[0].location == "Paris"
    assert jobs[1].location == "London · Paris"
    assert all(job.source == "rss" for job in jobs)


@responses.activate
def test_invalid_feed_raises_format_error() -> None:
    responses.get(URL, body="<html>Connexion</html>")
    with pytest.raises(ProviderFormatError, match="canal RSS absent"):
        RssProvider(make_http()).fetch_jobs(company("PayFit", "rss", url=URL))
