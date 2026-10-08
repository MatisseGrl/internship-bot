from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

import pytest

from internbot.config import CompanyConfig
from internbot.errors import ProviderError
from internbot.http import HttpClient
from internbot.models import Job
from internbot.providers.base import REGISTRY, Provider

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_http(**kwargs: Any) -> HttpClient:
    """Client HTTP sans attente réelle (délais et backoff neutralisés)."""
    sleeps: list[float] = []
    client = HttpClient(min_delay_s=0, sleep=sleeps.append, **kwargs)
    client.sleeps = sleeps  # type: ignore[attr-defined]
    return client


def company(name: str = "Acme", provider: str = "fake", **opts: Any) -> CompanyConfig:
    return CompanyConfig(name=name, provider=provider, **opts)


def job(
    job_id: str,
    title: str = "Software Engineer Intern",
    company_name: str = "Acme",
    location: str = "Paris, France",
    **kw: Any,
) -> Job:
    return Job(
        company=company_name,
        job_id=job_id,
        title=title,
        url=f"https://example.com/jobs/{job_id}",
        source="fake",
        location=location,
        **kw,
    )


class FakeProvider(Provider):
    """Provider de test : renvoie `jobs[company]` ou lève `errors[company]`."""

    name = "fake"
    optional_fields = ("note",)
    jobs: ClassVar[dict[str, list[Job]]] = {}
    errors: ClassVar[dict[str, Exception]] = {}
    enriched: ClassVar[list[str]] = []

    def fetch_jobs(self, company: CompanyConfig) -> list[Job]:
        if company.name in self.errors:
            raise self.errors[company.name]
        return list(self.jobs.get(company.name, []))

    def enrich(self, company: CompanyConfig, job: Job) -> Job:
        FakeProvider.enriched.append(job.job_id)
        return job


@pytest.fixture(autouse=True)
def fake_provider() -> Any:
    REGISTRY["fake"] = FakeProvider
    FakeProvider.jobs = {}
    FakeProvider.errors = {}
    FakeProvider.enriched = []
    yield FakeProvider
    REGISTRY.pop("fake", None)


__all__ = ["FakeProvider", "ProviderError", "company", "job", "load_fixture", "make_http"]
