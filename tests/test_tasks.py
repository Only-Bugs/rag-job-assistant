"""Task assembly, validation and retry — with a scripted fake model (no Ollama)."""

from __future__ import annotations

import re

import pytest

from resumate.evaluation.checks import format_problems, markdown_leaks, parse_emails
from resumate.services import tasks as tasks_mod
from resumate.services.analysis import JobAnalysis, Pair
from resumate.services.evidence import EvidenceItem, EvidenceSet
from resumate.services.validate import clean_prose, ground_line, line_problems

E1 = EvidenceItem(id="E1", section="experience", role="Software Engineer", org="Acme",
                  text="Cut checkout latency from 2.4 seconds to under a second by adding a Redis cache, resulting in 12% more orders.",
                  tools=["Redis"], metrics=["2.4", "12%"])
E2 = EvidenceItem(id="E2", section="experience", role="Software Engineer", org="Acme",
                  text="Built a React admin panel used by 40+ store managers to publish promotions.",
                  tools=["React"], metrics=["40+"])
E3 = EvidenceItem(id="E3", section="projects", org="Pantry Planner", role="Developer",
                  text="Built a meal-planning web app in React that suggests recipes from pantry items.",
                  tools=["React"], metrics=[])


def _analysis(**kw) -> JobAnalysis:
    base = dict(
        role_title="Backend Developer", company="Tyro", jd_terms=["Redis", "React", "Kafka"],
        have=["Redis", "React"], missing=["Kafka"], requirements=["Experience with Redis caching", "React frontends"],
        coverage={}, match_score=0.7, band="Strong", top_gap="Experience with Kafka event streams",
        gap_terms=["Kafka"],
        pairs=[Pair("Experience with Redis caching", E1, 0.6), Pair("React frontends", E2, 0.5)],
        selected=[E1, E2, E3], core_stack=["Redis", "React"], domain_ok=True, domain_similarity=0.6,
    )
    base.update(kw)
    return JobAnalysis(**base)


def _ctx(**kw):
    return tasks_mod.TaskContext(
        shared_prefix="PREFIX", analysis=_analysis(**kw),
        evidence=EvidenceSet(items=[E1, E2, E3], skills=["Redis", "React", "Python"]),
        profile={"name": "Alex Example", "title": "Software Engineer", "skills": ["Python"]},
    )


@pytest.fixture()
def fake_model(monkeypatch):
    """Route each call to a scripted reply chosen by matching the TASK text."""
    calls: list[dict] = []
    script: list[tuple[str, str]] = []

    def fake_chat_stream(messages, *, options=None, prefill=None, format=None, task_name="", stage=""):
        prompt = messages[-1]["content"]
        calls.append({"prompt": prompt, "prefill": prefill, "options": options, "task": task_name})
        for pattern, reply in script:
            if re.search(pattern, prompt, re.S):
                if isinstance(reply, list):  # successive replies for retries
                    reply = reply.pop(0) if len(reply) > 1 else reply[0]
                yield from [reply[i:i + 7] for i in range(0, len(reply), 7)]
                return
        yield "Generic sentence."

    monkeypatch.setattr(tasks_mod, "chat_stream", fake_chat_stream)
    return script, calls


def _drain(gen):
    tokens, final = [], None
    for name, val in gen:
        if name == "token":
            tokens.append(val["chunk"])
        else:
            final = val
    return "".join(tokens), final


def test_cover_prefills_greeting_strips_markdown_and_signs_off(fake_model):
    script, calls = fake_model
    script.append(("Cover|cover letter", "I am excited about **Redis** work at Tyro.\n\nAt Acme I cut latency.\n\nI would love to talk.\n\nExtra para."))
    _, final = _drain(tasks_mod.run_cover(_ctx()))
    assert calls[0]["prefill"] == "Dear Hiring Manager,\n\n"
    assert "Sincerely" in calls[0]["options"]["stop"]
    assert final.startswith("Dear Hiring Manager,\n\n") and final.endswith("Sincerely,\nAlex Example")
    assert "**" not in final and "Extra para" not in final  # exactly 3 body paragraphs
    assert not format_problems("cover", final)


def test_emails_three_calls_contract_format(fake_model):
    script, calls = fake_model
    script.append(("application email", "Applying for Backend Developer\n\nDear [Name],\nI am applying. I cut latency by 12%."))
    script.append(("cold email", "20+ Years Building Caches\n\nHi Sam,\nI built caching. Could we talk?"))
    script.append(("follow-up", "Following up\n\nHello,\nJust checking in. Thanks!"))
    streamed, final = _drain(tasks_mod.run_emails(_ctx()))
    assert [c["prefill"] for c in calls] == ["Subject: "] * 3
    emails = parse_emails(final)
    assert [e["index"] for e in emails] == [1, 2, 3]
    assert emails[0]["subject"] == "Applying for Backend Developer"
    assert emails[0]["body"].startswith("Dear Hiring Manager,") and "[Name]" not in emails[0]["body"]
    assert emails[1]["body"].startswith("Hi there,")
    assert emails[1]["subject"].startswith("Backend Developer at Tyro")  # "20+" not in its evidence -> fallback
    assert final.count("Best regards,\nAlex Example") == 3
    assert len(parse_emails(streamed)) == 3  # the live stream parses too
    assert not markdown_leaks(final)


def test_skills_sections_bullets_validated_and_retried(fake_model):
    script, calls = fake_model
    script.append(("one sentence to the candidate", "are a strong match for this role."))
    # E1 bullet: first answer invents 40% and Kafka -> retried; retry is clean.
    script.append((r"Rewrite evidence \[E1\].*Problems", "Added a Redis cache that cut checkout latency, lifting orders 12%."))
    script.append((r"Rewrite evidence \[E1\]", "Improved checkout 40% using Kafka and Redis."))
    script.append((r"Rewrite evidence \[E2\]", "Built a React admin panel for 40+ store managers."))
    script.append((r"Rewrite evidence \[E3\]", "Built a React meal-planning app that cut food waste by 30%."))
    script.append(("biggest gap", "You could build a small Kafka demo project."))
    ctx = _ctx()
    _, final = _drain(tasks_mod.run_skills(ctx))
    for sec in ("## Match Snapshot", "## ATS Keywords", "## Tailored Resume Bullets", "## Gap to Close"):
        assert sec in final
    assert "**Missing from your profile:** Kafka" in final
    assert final.split("## Match Snapshot\n")[1].startswith("You are a strong match")
    bullets = [l for l in final.split("\n") if l.startswith("- ") and "**" not in l]
    assert len(bullets) == 3  # 2 pairs + 1 filler from selected evidence
    assert "40%" not in final and "Kafka and Redis" not in final      # retried away
    assert "lifting orders 12%" in final
    assert "30%" not in final and "[add metric]" in final             # E3 grounded after failed retry
    assert any("bullet3" in f for f in ctx.flags)
    retry_prompts = [c for c in calls if "Problems:" in c["prompt"]]
    assert retry_prompts and "40%" in retry_prompts[0]["prompt"]


def test_ats_prefills_title_core_stack_from_code(fake_model):
    script, _ = fake_model
    script.append(("resume summary", " 3 years building Redis-backed services. Strong React skills. Third sentence."))
    script.append((r"outcome line from evidence \[E3\]", "Built a meal-planning web app in React."))
    script.append((r"outcome line from evidence \[E1\]", "Cut checkout latency with a Redis cache, lifting orders 12%."))
    script.append((r"outcome line from evidence \[E2\]", "Built a React admin panel for 40+ store managers."))
    _, final = _drain(tasks_mod.run_ats(_ctx()))
    # "3 years" isn't in any evidence, so that (prefilled) sentence is replaced by a factual opener.
    assert final.startswith("Software Engineer with hands-on experience in Redis, React.")
    assert "3 years" not in final and "Strong React skills." in final
    assert "Third sentence" not in final
    assert "Core Stack: Redis, React" in final
    assert not format_problems("ats", final)


def test_validator_rules():
    assert line_problems("Cut latency by 12% using Redis.", E1, ["Python"]) == []
    probs = line_problems("Improved latency 40% with Kafka.", E1, ["Python"])
    assert any("40%" in p for p in probs) and any("Kafka" in p for p in probs)
    assert any("past-tense" in p for p in line_problems("Responsible for Redis caching.", E1, []))
    assert ground_line("Cut latency 40% and orders 12%.", E1) == "Cut latency [add metric] and orders 12%."
    text, flags = clean_prose("## Hi\n**Bold** line. Contact [Hiring Manager] today. Thanks.")
    assert text == "Hi\nBold line. Thanks." and flags


def test_unsupported_tool_falls_back_to_evidence_wording(fake_model):
    script, _ = fake_model
    script.append((r"Rewrite evidence \[E2\]", "Built a React admin panel on AWS Lambda for store managers."))
    ctx = _ctx()
    line = tasks_mod._validated_line(ctx, "skills", "TASK: Rewrite evidence [E2] (x)", E2, label="b")
    assert line == E2.text  # AWS/Lambda not in E2 twice -> candidate's own bullet
    assert any("AWS" in f for f in ctx.flags)


def test_bare_number_matches_plus_metric():
    from resumate.services.validate import drop_unsupported
    text, removed = drop_unsupported("I fixed over 12,000 duplicate rows. I cut costs 50%.", grounding="fixing 12,000+ duplicate rows")
    assert text == "I fixed over 12,000 duplicate rows." and len(removed) == 1
