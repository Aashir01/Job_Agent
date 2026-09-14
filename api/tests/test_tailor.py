"""§10: 'Resume output must be traceable to bullet_bank. No exceptions,
no reasonable inference.' These tests are that rule."""
from __future__ import annotations

from app.agents.tailor import Tailor, _words, verify_rewrite
from app.llm.router import LLMRouter

JD = _words("retrieval augmented generation RAG LangChain FastAPI evaluation latency pipeline")
ORIGINAL = "Built a RAG pipeline in Python cutting document lookup time by 38%."


def test_accepts_a_reword_that_only_mirrors_jd_vocabulary():
    ok, why = verify_rewrite(
        ORIGINAL,
        "Built a retrieval augmented generation pipeline in Python, cutting document lookup latency by 38%.",
        JD,
    )
    assert ok, why


def test_rejects_an_inflated_metric():
    ok, why = verify_rewrite(
        ORIGINAL, "Built a RAG pipeline in Python cutting document lookup time by 62%.", JD
    )
    assert not ok and "figure" in why


def test_rejects_an_invented_technology():
    ok, why = verify_rewrite(
        ORIGINAL, "Built a RAG pipeline in Python on Kubernetes cutting lookup time by 38%.", JD
    )
    assert not ok and "kubernetes" in why.lower()


def test_rejects_an_invented_scope_claim():
    ok, why = verify_rewrite(
        ORIGINAL, "Led a team building a RAG pipeline in Python cutting lookup time by 38%.", JD
    )
    assert not ok


def test_rejects_a_ballooning_rewrite():
    ok, why = verify_rewrite(ORIGINAL, ORIGINAL + " " + ORIGINAL + " " + ORIGINAL, JD)
    assert not ok and "longer" in why


def test_rejects_an_empty_rewrite():
    assert verify_rewrite(ORIGINAL, "   ", JD)[0] is False


def test_an_unchanged_bullet_always_passes():
    assert verify_rewrite(ORIGINAL, ORIGINAL, JD)[0] is True


async def test_a_rejected_rewrite_falls_back_to_the_user_s_own_words(db, settings, profile):
    """The fabrication never reaches the document — and the attempt is recorded."""
    db.rpc_returns["match_bullets"] = [
        {"id": "b1", "role_context": "Acme", "text": ORIGINAL, "metric": "38%",
         "tags": ["rag"], "strength": 5, "similarity": 0.9}
    ]

    class FabricatingLLM(LLMRouter):
        async def generate_json(self, prompt, **kw):
            return {"bullets": [{"id": "b1", "text": "Architected a Kubernetes RAG platform for 40 teams."}]}

    tailor = Tailor(db, FabricatingLLM(settings, db), settings)
    result = await tailor.tailor(
        {"id": "j1", "title": "AI Engineer", "description": "RAG work"},
        {"required_skills": ["RAG"], "resume_keywords": ["RAG"]},
        profile,
    )
    assert len(result.bullets) == 1
    bullet = result.bullets[0]
    assert bullet.final == ORIGINAL
    assert bullet.rejected_rewrite is not None
    assert result.rejected == 1
    assert result.diff["rejected_rewrites"] == 1
    assert result.docx[:2] == b"PK"


async def test_every_rendered_bullet_carries_its_source_id(db, settings, profile):
    db.rpc_returns["match_bullets"] = [
        {"id": "b1", "role_context": "Acme", "text": ORIGINAL, "strength": 5, "similarity": 0.9},
        {"id": "b2", "role_context": "Acme", "text": "Shipped an evaluation harness.",
         "strength": 4, "similarity": 0.7},
    ]

    class SilentLLM(LLMRouter):
        async def generate_json(self, prompt, **kw):
            return {"bullets": []}

    result = await Tailor(db, SilentLLM(settings, db), settings).tailor(
        {"id": "j1", "title": "AI Engineer", "description": "RAG"},
        {"required_skills": ["RAG"], "resume_keywords": []},
        profile,
    )
    ids = {e["bullet_id"] for e in result.diff["entries"]}
    assert ids == {"b1", "b2"}
    assert all(e["final"] for e in result.diff["entries"])


async def test_skills_section_never_claims_an_unevidenced_skill(db, settings, profile):
    """§10: never keyword-stuff."""
    db.rpc_returns["match_bullets"] = [
        {"id": "b1", "role_context": "Acme", "text": ORIGINAL, "strength": 5, "similarity": 0.9}
    ]

    class SilentLLM(LLMRouter):
        async def generate_json(self, prompt, **kw):
            return {"bullets": []}

    tailor = Tailor(db, SilentLLM(settings, db), settings)
    result = await tailor.tailor(
        {"id": "j1", "title": "AI Engineer", "description": "x"},
        {"required_skills": ["Python", "Kubernetes", "Terraform"], "resume_keywords": ["Helm"]},
        {**profile, "skills": []},
    )
    assert "Python" in result.skills
    assert "Kubernetes" not in result.skills
    assert "Helm" not in result.skills
