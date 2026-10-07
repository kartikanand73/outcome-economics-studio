"""Shared model catalog: seeding, editing with history, restore, and use in scenarios."""
import os
from decimal import Decimal as D

os.environ["OES_DB_PATH"] = ":memory:"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.api.main import app, catalog  # noqa: E402
from app.domain.models import CatalogModel, Evidence, Tier  # noqa: E402
from app.engine.aggregate import calculate  # noqa: E402
from app.pricing.model_catalog import CatalogStore, load_seed, to_model_config  # noqa: E402
from app.samples.catalog import outcome_aware_router  # noqa: E402

client = TestClient(app)


@pytest.fixture
def cat():
    s = CatalogStore(":memory:")
    s.seed()
    return s


def test_seed_has_many_providers_with_sources_and_dates(cat):
    items = cat.list()
    providers = {m.provider for m in items}
    assert {"OpenAI", "Anthropic", "Google", "xAI", "Mistral", "DeepSeek", "Custom"} <= providers
    for m in items:
        assert m.as_of, m.id
        if m.provider != "Custom":
            assert m.source_url.startswith("https://"), m.id
            assert m.evidence == Evidence.PROVIDER
    jev = cat.get("custom-jev-1-13")
    assert jev.evidence == Evidence.ASSUMPTION


def test_seed_never_overwrites_your_edits(cat):
    m = cat.get("openai-gpt-6-1-sol")
    m.input_price_per_m = D("1.50")
    cat.update(m.id, m, note="contract price")
    assert cat.seed() == 0
    assert cat.get(m.id).input_price_per_m == D("1.50")


def test_price_edit_records_history_and_marks_edited(cat):
    m = cat.get("anthropic-claude-sonnet-5-5")
    old_in = m.input_price_per_m
    m.input_price_per_m = D("1.80")
    saved = cat.update(m.id, m, note="negotiated")
    assert saved.edited is True
    assert saved.history[-1].input_price_per_m == old_in
    assert saved.history[-1].note == "negotiated"
    # a non-price edit adds no history
    saved.notes = "used for second opinions"
    again = cat.update(m.id, saved)
    assert len(again.history) == 1


def test_restore_puts_published_price_back_and_keeps_history(cat):
    m = cat.get("google-gemini-3-5-flash")
    published = m.input_price_per_m
    m.input_price_per_m = D("9.99")
    cat.update(m.id, m)
    cat.restore(m.id)
    r = cat.get(m.id)
    assert r.input_price_per_m == published and r.edited is False
    assert len(r.history) == 2


def test_add_new_model_gets_unique_id(cat):
    a = cat.create(CatalogModel(provider="Azure OpenAI", name="GPT-6.1 Sol (PTU)", tier=Tier.LARGER,
                                input_price_per_m=D("1.80"), output_price_per_m=D("9.00"),
                                evidence=Evidence.ASSUMPTION))
    b = cat.create(CatalogModel(provider="Azure OpenAI", name="GPT-6.1 Sol (PTU)", tier=Tier.LARGER,
                                input_price_per_m=D("1.80"), output_price_per_m=D("9.00")))
    assert a.id == "azure-openai-gpt-6-1-sol-ptu" and b.id == a.id + "-2"
    assert a.is_seed is False and a.as_of


def test_catalog_model_config_is_bounded_and_carries_price_evidence(cat):
    entry = cat.get("anthropic-claude-opus-5-5")
    mc = to_model_config(entry)
    assert mc.catalog_id == entry.id and mc.catalog_as_of == entry.as_of
    assert mc.input_price_per_m == D("4.00") and mc.output_price_per_m == D("20.00")
    assert mc.ev("input_price_per_m") == Evidence.PROVIDER
    assert mc.ev("avg_input_tokens") == Evidence.ASSUMPTION
    # drop it into the router in place of Sol: still bounded, still valid
    sc = outcome_aware_router()
    sc.models.append(mc)
    sc.routes[2].stages[1].model_id = mc.id
    r = calculate(sc)
    assert r["ok"] and not r["summary"]["max_cost_per_task"]["unbounded"]


def test_every_seed_model_works_as_a_stage(cat):
    for entry in load_seed():
        sc = outcome_aware_router()
        mc = to_model_config(entry, model_id="x")
        sc.models.append(mc)
        sc.routes[2].stages[1].model_id = "x"
        r = calculate(sc)
        assert r["ok"], entry.id
        assert not r["summary"]["max_cost_per_task"]["unbounded"], entry.id


# ---------------------------------------------------------------- API
def test_catalog_api_crud_and_restore():
    catalog.restore()
    lst = client.get("/api/catalog").json()
    assert len(lst) >= 15
    sol = next(m for m in lst if m["id"] == "openai-gpt-6-1-sol")
    sol["input_price_per_m"] = "1.75"
    sol["change_note"] = "EA discount"
    upd = client.put("/api/catalog/openai-gpt-6-1-sol", json=sol).json()
    assert upd["input_price_per_m"] == "1.75" and upd["edited"] is True and upd["history"][-1]["note"] == "EA discount"
    new = client.post("/api/catalog", json={"provider": "Meta (via Azure)", "name": "Llama 5 70B", "tier": "lightweight",
                                            "input_price_per_m": "0.40", "output_price_per_m": "0.60",
                                            "evidence": "assumption"})
    assert new.status_code == 201
    nid = new.json()["id"]
    cfg = client.get(f"/api/catalog/{nid}/model-config").json()
    assert cfg["catalog_id"] == nid and cfg["input_price_per_m"] == "0.40"
    bad = client.post("/api/catalog", json={"provider": "X", "name": "Y", "input_price_per_m": "-1",
                                            "output_price_per_m": "1"})
    assert bad.status_code == 422
    assert client.delete(f"/api/catalog/{nid}").status_code == 200
    restored = client.post("/api/catalog/openai-gpt-6-1-sol/restore").json()
    assert restored["input_price_per_m"] == "2.00"
    assert client.post(f"/api/catalog/{nid}/restore").status_code == 404
    assert client.get("/api/pricing/catalog/models").status_code == 200
