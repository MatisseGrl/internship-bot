from __future__ import annotations

import pytest

from internbot.config import FiltersConfig
from internbot.filters import JobClassifier, TermMatcher, normalize
from internbot.filters_v3 import DROP, NOTIFY, REVIEW
from tests.conftest import job


def make_classifier(**kw: object) -> JobClassifier:
    base: dict[str, object] = {
        "title_exclude": ["senior", "staff", "principal", "manager", "director"],
        "year_hint": [],
    }
    base.update(kw)
    return JobClassifier(FiltersConfig(**base))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Stagiaire Développeur", "stagiaire developpeur"),
        ("CO-OP / Été 2027", "co op ete 2027"),
        ("  Ingénieur   ÉLÈVE ", "ingenieur eleve"),
    ],
)
def test_normalize(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


@pytest.mark.parametrize(
    ("title", "status"),
    [
        ("Software Engineer Intern", NOTIFY),
        ("INTERN - Backend", NOTIFY),
        ("Stagiaire Développeur", NOTIFY),
        ("Co-op Software Developer", NOTIFY),
        ("Internal Tools Engineer", DROP),  # « internal » ne doit pas matcher « intern »
        ("Senior Software Engineer Intern", DROP),  # title_exclude de la config
        ("Staff Engineer Intern Program", DROP),
        ("Engineering Manager, Interns", DROP),
    ],
)
def test_title_verdict(title: str, status: str) -> None:
    assert make_classifier().title_verdict(title).status == status, title


def test_title_exclude_reason_mentions_the_word() -> None:
    assert make_classifier().title_verdict("Senior SWE Intern").reason == "titre exclu ('senior')"


@pytest.mark.parametrize(
    ("mode", "title", "ok"),
    [
        ("prefer", "Summer 2027 Software Intern", True),
        ("prefer", "Software Intern", True),  # pas d'année : gardé
        ("prefer", "Summer 2026 Software Intern", False),  # autre saison explicite
        ("prefer", "2026/2027 Software Intern", True),
        ("require", "Software Intern", False),
        ("require", "Software Intern (2027)", True),
        ("off", "Summer 2026 Software Intern", True),
    ],
)
def test_year_hint(mode: str, title: str, ok: bool) -> None:
    f = make_classifier(year_hint=["2027"], year_hint_mode=mode)
    assert (f.title_verdict(title).status != DROP) is ok


def test_classify_uses_location_and_regions() -> None:
    f = make_classifier()
    assert f.classify(job("1", location="Paris, France")).status == NOTIFY
    assert f.classify(job("2", location="Bangalore, India")).status == DROP
    assert f.classify(job("3", location="")).status == REVIEW  # lieu inconnu : à vérifier
    assert make_classifier(regions=["uk"]).classify(job("4", location="Paris")).status == DROP


def test_partial_location_is_reviewed_not_dropped() -> None:
    # Workday « 3 Locations » non résolu : ni notifié à l'aveugle, ni jeté.
    j = job("1", location="3 Locations", location_complete=False)
    assert make_classifier().classify(j).status == REVIEW


def test_config_switches_are_passed_to_v3() -> None:
    title = "Data Analyst Intern"
    assert make_classifier().classify(job("1", title=title)).status == NOTIFY
    assert make_classifier(include_data=False).classify(job("1", title=title)).status == REVIEW
    fde = job("2", title="Forward Deployed Engineer Intern")
    assert make_classifier(include_fde=False).classify(fde).status == NOTIFY  # « engineer »
    qr = job("3", title="Quantitative Research Intern")
    assert make_classifier().classify(qr).status == DROP
    assert make_classifier(include_quant_research=True).classify(qr).status == NOTIFY


def test_ai_priority() -> None:
    v = make_classifier().classify(job("1", title="Machine Learning Engineer Intern"))
    assert v.status == NOTIFY and v.priority


def test_term_matcher_prefers_longest_term() -> None:
    m = TermMatcher(["machine", "machine learning"])
    assert m.find("Machine Learning Intern") == "machine learning"
    assert not TermMatcher([])
    assert TermMatcher([" ", ""]).find("anything") is None
