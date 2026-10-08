from __future__ import annotations

import pytest

from internbot.config import FiltersConfig
from internbot.filters import JobFilter, TermMatcher, normalize
from tests.conftest import job


def make_filter(**kw: object) -> JobFilter:
    base: dict[str, object] = {
        "title_include": ["intern", "internship", "stage", "stagiaire", "co-op", "working student"],
        "title_exclude": ["senior", "staff", "principal", "manager", "director"],
        "keywords_any": [],
        "year_hint": [],
    }
    base.update(kw)
    return JobFilter(FiltersConfig(**base))  # type: ignore[arg-type]


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
    ("title", "ok"),
    [
        ("Software Engineer Intern", True),
        ("INTERN - Backend", True),
        ("Internship, Data", True),
        ("Stage - Ingénieur logiciel", True),
        ("STAGIAIRE Développeur", True),
        ("Stagiaire développeuse", True),
        ("Co-op Software Developer", True),
        ("Coop Software Developer", False),  # « co-op » ≠ « coop » (mot différent)
        ("Working Student Data Engineering", True),
        ("Internal Tools Engineer", False),  # « internal » ne doit pas matcher « intern »
        ("International Sales", False),
        ("Senior Software Engineer", False),
        ("Staff Engineer Intern Program", False),  # exclusion prioritaire
        ("Engineering Manager, Interns", False),
        ("Stagecoach Driver", False),  # mot entier
    ],
)
def test_title_include_exclude(title: str, ok: bool) -> None:
    f = make_filter(
        title_include=[
            "intern",
            "interns",
            "internship",
            "stage",
            "stagiaire",
            "co-op",
            "working student",
        ]
    )
    assert (f.title_reject_reason(title) is None) is ok, title


def test_accents_in_terms_are_ignored_too() -> None:
    f = make_filter(title_include=["élève ingénieur"])
    assert f.title_reject_reason("Eleve Ingenieur - Data") is None
    assert f.title_reject_reason("ÉLÈVE-INGÉNIEUR R&D") is None


def test_keywords_any_whole_words() -> None:
    f = make_filter(keywords_any=["ml", "software", "full stack"])
    assert f.title_reject_reason("ML Intern") is None
    assert f.title_reject_reason("Full-Stack Intern") is None
    assert f.title_reject_reason("HTML Intern") is not None  # « ml » dans « html » : non
    assert f.title_reject_reason("Marketing Intern") is not None


def test_empty_include_accepts_everything_not_excluded() -> None:
    f = make_filter(title_include=[], title_exclude=["senior"])
    assert f.title_reject_reason("Data Engineer") is None
    assert f.title_reject_reason("Senior Data Engineer") is not None


@pytest.mark.parametrize(
    ("mode", "title", "ok"),
    [
        ("prefer", "Summer 2027 Intern", True),
        ("prefer", "Software Intern", True),  # pas d'année : gardé
        ("prefer", "Summer 2026 Intern", False),  # autre saison explicite
        ("prefer", "2026/2027 Intern", True),
        ("require", "Software Intern", False),
        ("require", "Intern (2027)", True),
        ("off", "Summer 2026 Intern", True),
    ],
)
def test_year_hint(mode: str, title: str, ok: bool) -> None:
    f = make_filter(year_hint=["2027"], year_hint_mode=mode)
    assert (f.title_reject_reason(title) is None) is ok


def test_locations() -> None:
    f = make_filter(locations_include=["France", "Remote", "Zürich"], locations_exclude=["Lyon"])
    assert f.matches(job("1", location="Paris, France"))
    assert f.matches(job("2", location="Remote - EMEA"))
    assert f.matches(job("3", location="Zurich, Switzerland"))  # accents ignorés
    assert not f.matches(job("4", location="New York, NY"))
    assert not f.matches(job("5", location="Lyon, France"))  # exclusion prioritaire
    assert f.matches(job("6", location=""))  # lieu inconnu : on garde
    assert f.matches(
        job("7", location="8 Locations", location_complete=False)
    )  # partiel : on garde


def test_no_location_filter_accepts_all() -> None:
    assert make_filter().matches(job("1", location="Tokyo"))


def test_term_matcher_prefers_longest_term() -> None:
    m = TermMatcher(["machine", "machine learning"])
    assert m.find("Machine Learning Intern") == "machine learning"
    assert not TermMatcher([])
    assert TermMatcher([" ", ""]).find("anything") is None


def test_exclusion_multi_location_rejects_only_if_all_places_excluded() -> None:
    f = make_filter(locations_exclude=["China", "Shanghai", "Beijing"])
    assert not f.matches(job("1", location="China, Shanghai"))
    assert not f.matches(job("2", location="China - Beijing · China - Shanghai"))
    assert not f.matches(job("3", location="Shanghai"))  # ville seule
    assert f.matches(job("4", location="China, Shanghai · US, CA, Santa Clara"))
    assert f.matches(job("5", location="Beijing; Paris, France"))  # séparateur Greenhouse
    assert f.matches(job("6", location="Taiwan, Taipei"))
    assert f.matches(job("7", location="2 Locations", location_complete=False))


def test_include_applies_to_non_excluded_parts() -> None:
    f = make_filter(locations_include=["France"], locations_exclude=["China"])
    assert f.matches(job("1", location="China, Shanghai · Paris, France"))
    assert not f.matches(job("2", location="China, Shanghai · US, Seattle"))


def test_classify_notify_review_reject() -> None:
    from internbot.filters import NOTIFY, REJECT, REVIEW

    f = JobFilter(
        FiltersConfig(
            keywords_any=["software"],
            year_hint=["2027"],
            locations_exclude=["China"],
        )
    )
    assert f.classify(job("1", "Software Engineer Intern")) == NOTIFY
    assert f.classify(job("2", "Marketing Intern")) == REVIEW  # stage hors keywords_any
    assert f.classify(job("3", "Software Intern, Summer 2026")) == REVIEW  # autre saison
    assert f.classify(job("4", "Senior Software Engineer")) == REJECT  # pas un stage
    assert f.classify(job("5", "Software Engineer Intern", location="Shanghai, China")) == REJECT
