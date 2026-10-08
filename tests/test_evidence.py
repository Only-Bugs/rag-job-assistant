"""Tests for deterministic resume segmentation and evidence selection helpers."""

from __future__ import annotations

import json
from pathlib import Path

from resumate.services.evidence import EvidenceItem, _dedupe, build_evidence, segment_text

FIXTURES = Path(__file__).parent / "fixtures" / "eval"

# Mimics pypdf output of a two-column-free resume: ALL CAPS sections, role lines
# with a date range, an org line with a trailing location, ▪ bullets whose text
# wraps onto continuation lines, and a projects block with name + role lines.
PDF_LIKE = """Alex Example  |  Full Stack Developer
Sydney, NSW 2000 | alex@example.com
CAREER SUMMARY
▪Full stack developer with commercial experience in retail software and
internal tooling.
KEY SKILLS
▪Web - React, TypeScript, Node.js
▪Data - PostgreSQL, Redis
WORK EXPERIENCE
Software Engineer Mar 2023 – Present
Acme Retail Pty Ltd Sydney, NSW
Online retailer with 200 stores.
▪Cut checkout latency from 2.4 seconds to 600ms, by adding a Redis cache in front of the
pricing service, resulting in 12% more completed orders.
▪Built a React and TypeScript admin panel used by 40+ store managers to publish
promotions without engineering help.
Graduate Developer Jan 2022 – Feb 2023
Bluegum Software Melbourne, VIC
▪Migrated 3 legacy reports from Excel macros to a Node.js service backed by
PostgreSQL.
EDUCATION
Bachelor of Computer Science - UNSW. 2018 – 2021
PROJECTS
Pantry Planner
Developer
▪Built a meal-planning web app in React that suggests recipes from what is
already in the pantry.
"""


def _by_text(items, needle):
    return next(it for it in items if needle in it.text)


def test_segment_pdf_like_roles_bullets_and_projects():
    items, skills = segment_text(PDF_LIKE, "resume.pdf")
    checkout = _by_text(items, "checkout latency")
    assert checkout.role == "Software Engineer"
    assert checkout.org == "Acme Retail Pty Ltd"          # location stripped
    assert checkout.dates.startswith("Mar 2023")
    # Wrapped continuation line re-joined into the bullet.
    assert "12% more completed orders" in checkout.text
    assert _by_text(items, "Excel macros").org == "Bluegum Software"
    pantry = _by_text(items, "meal-planning")
    assert (pantry.org, pantry.role) == ("Pantry Planner", "Developer")
    # Role description lines and education are not evidence.
    assert not any("200 stores" in it.text for it in items)
    assert not any("UNSW" in it.text for it in items)
    assert {"React", "TypeScript", "Node.js", "PostgreSQL", "Redis"} <= set(skills)


def test_build_evidence_extracts_tools_metrics_and_ids(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "resume.txt").write_text(PDF_LIKE)
    ev = build_evidence(tmp_path / "docs", {"skills": ["Redis"], "achievements": []})
    items = ev.items
    assert {"React", "PostgreSQL", "Redis"} <= set(ev.skills)
    assert [it.id for it in items] == [f"E{i}" for i in range(1, len(items) + 1)]
    checkout = _by_text(items, "checkout latency")
    assert "Redis" in checkout.tools
    assert "12%" in checkout.metrics and "2.4" in checkout.metrics
    assert "600ms" not in checkout.metrics  # number glued to a unit word is not matched by design
    assert "[E" in checkout.render() and "Metrics:" in checkout.render()


def test_markdown_resume_fixture_segments():
    d = FIXTURES / "profiles" / "data_dev"
    items = build_evidence(d / "profile_docs", json.loads((d / "profile_settings.json").read_text())).items
    freight = _by_text(items, "freight cost report")
    assert (freight.role, freight.org) == ("Data Analyst", "Freightline Logistics")
    assert {"6", "40"} <= set(freight.metrics)
    tracker = _by_text(items, "rental listings")
    assert tracker.org == "Rental Price Tracker"
    assert any(it.section == "settings" for it in items)


def test_dedupe_merges_rephrased_duplicates_in_same_role():
    a = EvidenceItem(id="", section="experience", role="SDE", org="Acme",
                     text="Moved 5,000+ travel agents off phone bookings, by shipping a self-serve storefront in PHP across 60,000+ products, resulting in four roles redirected to fulfilment.")
    b = EvidenceItem(id="", section="experience", role="SDE", org="Acme",
                     text="Scaled booking from one agent per call to 5,000+, by shipping a self-serve storefront across 60,000+ products, redirecting four full-time roles to fulfilment.")
    c = EvidenceItem(id="", section="experience", role="SDE", org="Acme",
                     text="Architected an e-commerce checkout flow, consolidating scattered purchase logic into one MVC path.")
    kept = _dedupe([a, b, c])
    assert len(kept) == 2 and c in kept
