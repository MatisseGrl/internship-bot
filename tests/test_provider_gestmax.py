"""Contrat de lecture du tableau et de la pagination MBDA France."""

from __future__ import annotations

import pytest
import responses

from internbot.errors import ProviderFormatError
from internbot.providers.gestmax import GestmaxProvider, parse_results
from tests.conftest import FIXTURES, company, make_http

BASE = "https://mbda.gestmax.fr"


def _page(number: int) -> str:
    return (FIXTURES / f"gestmax_page{number}.html").read_text(encoding="utf-8")


def test_parse_real_page() -> None:
    rows, total = parse_results(_page(1))
    assert total == 703
    assert len(rows) == 20
    assert rows[0]["id"] == "20206"
    assert rows[0]["title"].startswith("Stage Logiciel :")
    assert rows[0]["location"] == "Le Plessis Robinson (92)"
    assert rows[0]["date"] == "08/10/2026"


@responses.activate
def test_fetch_two_pages_with_stable_ids() -> None:
    responses.get(f"{BASE}/search/index", body=_page(1))
    responses.get(f"{BASE}/search/index/page/2", body=_page(2))
    jobs = GestmaxProvider(make_http()).fetch_jobs(
        company("MBDA France", "gestmax", base_url=BASE, max_pages=2)
    )
    assert len(jobs) == 40
    assert len({job.job_id for job in jobs}) == 40
    assert jobs[0].posted_at == "2026-10-08"
    assert jobs[0].source == "gestmax"
    assert jobs[0].url.startswith(f"{BASE}/20206/1/")


@responses.activate
def test_repeated_page_is_an_error() -> None:
    responses.get(f"{BASE}/search/index", body=_page(1))
    responses.get(f"{BASE}/search/index/page/2", body=_page(1))
    with pytest.raises(ProviderFormatError, match="pagination bloquée"):
        GestmaxProvider(make_http()).fetch_jobs(
            company("MBDA France", "gestmax", base_url=BASE, max_pages=2)
        )


@responses.activate
def test_missing_total_is_an_error() -> None:
    responses.get(f"{BASE}/search/index", body="<html><body>Connexion requise</body></html>")
    with pytest.raises(ProviderFormatError, match="total absent"):
        GestmaxProvider(make_http()).fetch_jobs(company("MBDA France", "gestmax", base_url=BASE))
