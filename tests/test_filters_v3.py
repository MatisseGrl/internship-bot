from __future__ import annotations

import pytest

from internbot.filters_v3 import (
    DROP,
    NOTIFY,
    REVIEW,
    FilterConfig,
    classify,
    classify_location,
    matches_query,
    norm,
)


@pytest.mark.parametrize(
    ("title", "location", "status", "priority"),
    [
        ("Software Engineer Intern (BS/MS/PhD)", "San Francisco, CA", NOTIFY, False),
        ("Machine Learning Intern - PhD", "London", DROP, False),
        ("Forward Deployed Engineer Intern", "New York", NOTIFY, False),
        ("Data Analyst Intern", "Sydney, Australia", NOTIFY, False),
        ("Hardware Performance Engineer Intern", "Austin, TX", DROP, False),
        ("Performance Engineer Intern", "Santa Clara, CA", DROP, False),
        ("GPU Software Performance Intern", "Munich", NOTIFY, False),
        ("Hardware Machine Learning Research Intern", "Chicago", REVIEW, True),
        ("AI Solution Architect Intern", "Paris, France", REVIEW, True),
        ("Software Engineer Intern, Machine Learning", "Melbourne, Australia", NOTIFY, True),
        ("Internal Tools Engineer", "London", DROP, False),
        ("Validation Engineer Intern", "Toronto", DROP, False),
        ("Embedded Software Engineer Intern", "Grenoble, France", NOTIFY, False),
        ("Silicon Hardware Engineering - Intern", "US, Oregon, Hillsboro", DROP, False),
        ("Software Engineer Intern, Backend", "Mexico City, Mexico", DROP, False),
        ("Machine Learning Intern", "BLANK,BLANK,Multiple Locations", REVIEW, True),
    ],
)
def test_classify_reference_cases(title: str, location: str, status: str, priority: bool) -> None:
    verdict = classify(title, location)
    assert verdict.status == status, f"{title} @ {location} -> {verdict}"
    if status != DROP:
        assert verdict.priority is priority


def test_drop_reasons_are_explicit() -> None:
    assert classify("Internal Tools Engineer", "London").reason == "pas un stage"
    assert classify("Machine Learning Intern - PhD", "London").reason == "PhD uniquement"
    assert classify("Software Engineer Intern, Backend", "Mexico City").reason == "hors zone"
    assert classify("Validation Engineer Intern", "Toronto").reason.startswith("hardware")


def test_software_signal_beats_hardware() -> None:
    assert classify("GPU Software Performance Intern", "Munich").status == NOTIFY
    assert classify("Hardware Engineer Intern", "Munich").status == DROP
    assert classify("Silicon Firmware Developer Intern", "Austin, TX").status == NOTIFY


def test_quant_research_dropped_but_quant_engineer_reviewed() -> None:
    assert classify("Quantitative Research Intern", "Chicago").status == DROP
    assert classify("Quantitative Trader Intern", "London").status == DROP
    assert classify("Quant Trading Engineer Intern", "London").status == REVIEW
    cfg = FilterConfig(include_quant_research=True)
    assert classify("Quantitative Research Intern", "Chicago", cfg).status == NOTIFY


def test_non_tech_dropped() -> None:
    for title in ("UX Research Intern", "Internal Audit Intern", "Sales Intern"):
        assert classify(title, "Paris").status == DROP, title


def test_locations_remote_unknown_and_disabled_regions() -> None:
    cfg = FilterConfig()
    assert classify_location("Remote - EMEA", cfg).status == NOTIFY
    assert classify_location("Hybrid", cfg).status == NOTIFY
    assert classify_location("", cfg).status == REVIEW
    assert classify_location("Multiple Locations", cfg).status == REVIEW
    assert classify_location("Tel Aviv, Israel", cfg).status == DROP  # désactivé par défaut
    assert classify_location("Tel Aviv, Israel", FilterConfig({"israel"})).status == NOTIFY
    assert classify_location("Shanghai, China", cfg).status == DROP
    # Offre multi-lieux : un seul lieu dans une zone suffit.
    assert classify_location("China, Shanghai · US, CA, Santa Clara", cfg).status == NOTIFY
    assert classify_location("Le Plessis Robinson (92)", cfg).status == NOTIFY
    assert classify_location("Bourges (18)", cfg).status == NOTIFY


def test_matching_is_whole_word_and_accent_insensitive() -> None:
    assert norm("Développeur C++ / Zürich") == " developpeur c++ zurich "
    assert classify("Stagiaire Développeur", "Zürich, Suisse").status == NOTIFY
    assert classify("Internal Systems Engineer", "London").status == DROP  # internal ≠ intern


def test_matches_query_reference_cases() -> None:
    known = {"Cisco"}
    assert not matches_query(
        "cisco", "Lyft", "Software Engineer Intern", "San Francisco, CA", known
    )
    assert matches_query("cisco", "Cisco", "Software Engineer Intern", "San Jose, CA", known)
    assert matches_query("paris", "Datadog", "SWE Intern", "Paris, France", known)


def test_matches_query_other_cases() -> None:
    known = {"Cisco", "Capital One"}
    assert matches_query("", "Lyft", "SWE Intern", "NYC", known)  # vide : tout passe
    assert matches_query("CAPITAL one", "Capital One", "Data Intern", "McLean, VA", known)
    assert not matches_query("capital one", "Lyft", "Capital One Intern", "NYC", known)
    assert matches_query("machine learning", "Lyft", "Machine Learning Intern", "NYC", known)
    assert not matches_query("fran", "Lyft", "SWE Intern", "San Francisco, CA", known)
