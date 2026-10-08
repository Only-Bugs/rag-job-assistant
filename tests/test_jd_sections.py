"""Tests for deterministic JD trimming."""

from __future__ import annotations

from pathlib import Path

import pytest

from resumate.services.jd_sections import parse_jd

JDS = Path(__file__).parent / "fixtures" / "eval" / "jds"


def test_long_jd_drops_boilerplate_and_keeps_requirements():
    raw = (JDS / "long_boilerplate_fullstack.txt").read_text()
    jd = parse_jd(raw)
    assert jd.structured
    assert len(jd.text) < len(raw) / 2
    for dropped in ("About Us", "Benefits and Perks", "How to Apply"):
        assert dropped in jd.dropped_sections
    assert "parental leave" not in jd.text and "equal opportunity" not in jd.text.lower()
    assert any("TypeScript" in r for r in jd.requirements)
    assert any("GraphQL" in r for r in jd.responsibilities)


@pytest.mark.parametrize("name,role,company", [
    ("fullstack_atlassian", "Software Engineer (Full Stack)", "Atlassian"),
    ("backend_api_payments", "Backend Developer", "Tyro Payments"),
    ("ml_engineer_adjacent", "Machine Learning Engineer (Applied LLMs)", "Canva"),
    ("long_boilerplate_fullstack", "Senior Full Stack Developer", "Seek Limited"),
    ("out_of_domain_nurse", "Registered Nurse", "Alfred Health"),
])
def test_role_and_company(name, role, company):
    jd = parse_jd((JDS / f"{name}.txt").read_text())
    assert (jd.role_title, jd.company) == (role, company)


def test_unstructured_jd_is_flagged_for_fallback():
    jd = parse_jd("We need someone great at Python and AWS to build things with us. Apply now.")
    assert not jd.structured
