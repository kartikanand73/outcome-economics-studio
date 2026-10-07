"""FastAPI application: scenarios, calculation, comparison, import/export, reports.

Also serves the built React frontend from ``frontend/dist`` when present.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, ValidationError

from app.domain.models import CatalogModel, Scenario
from app.engine.aggregate import calculate
from app.engine.compare import compare
from app.importers.adapters import ImportError_, apply_import, parse_benchmark_json, parse_csv
from app.persistence.store import ScenarioStore
from app.pricing.catalog import PROVIDERS
from app.pricing.model_catalog import CatalogPriceProvider, CatalogStore, to_model_config
from app.reports.html_report import render_report
from app.reports.serialize import dumps, results_csv
from app.samples.catalog import new_scenario_template

APP_VERSION = "0.5.0"
app = FastAPI(title="Outcome Economics Studio", version=APP_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])

store = ScenarioStore(os.environ.get("OES_DB_PATH", str(Path(__file__).resolve().parents[2] / "data" /
                                                             "scenarios.db")))
store.seed_samples()
catalog = CatalogStore(store.path)
catalog.seed()
PROVIDERS["catalog"] = CatalogPriceProvider(catalog)


class JSON(Response):
    media_type = "application/json"

    def render(self, content) -> bytes:
        return dumps(content).encode()


def _get(sid: str) -> Scenario:
    sc = store.get(sid)
    if sc is None:
        raise HTTPException(404, f"Scenario '{sid}' not found")
    return sc


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "scenario"


# ------------------------------------------------------------------ scenarios
@app.get("/api/health")
def health():
    return {"status": "ok", "version": APP_VERSION}


@app.get("/api/scenarios", response_class=JSON)
def list_scenarios():
    return JSON(store.list())


@app.get("/api/scenarios/template", response_class=JSON)
def template():
    return JSON(new_scenario_template().model_dump(mode="json"))


@app.post("/api/scenarios", response_class=JSON, status_code=201)
def create_scenario(sc: Scenario):
    sc.is_sample = False
    return JSON(store.create(sc).model_dump(mode="json"), status_code=201)


@app.get("/api/scenarios/{sid}", response_class=JSON)
def get_scenario(sid: str):
    return JSON(_get(sid).model_dump(mode="json"))


@app.put("/api/scenarios/{sid}", response_class=JSON)
def update_scenario(sid: str, sc: Scenario):
    existing = _get(sid)
    # the imported benchmark is frozen: edits to inputs can never rewrite it
    sc.benchmark = existing.benchmark
    return JSON(store.update(sid, sc).model_dump(mode="json"))


@app.delete("/api/scenarios/{sid}")
def delete_scenario(sid: str):
    if not store.delete(sid):
        raise HTTPException(404, "not found")
    return {"deleted": sid}


class CloneBody(BaseModel):
    name: str | None = None


@app.post("/api/scenarios/{sid}/clone", response_class=JSON, status_code=201)
def clone_scenario(sid: str, body: CloneBody | None = None):
    sc = store.clone(sid, body.name if body else None)
    if sc is None:
        raise HTTPException(404, "not found")
    return JSON(sc.model_dump(mode="json"), status_code=201)


@app.delete("/api/scenarios/{sid}/benchmark", response_class=JSON)
def remove_benchmark(sid: str):
    sc = _get(sid)
    sc.benchmark = None
    return JSON(store.update(sid, sc).model_dump(mode="json"))


@app.post("/api/samples/reset", response_class=JSON)
def reset_samples():
    store.seed_samples(force=True)
    return JSON(store.list())


# ------------------------------------------------------------------ calculation
@app.post("/api/calculate", response_class=JSON)
def calculate_unsaved(sc: Scenario):
    """Calculate a scenario straight from the editor without saving it."""
    return JSON(calculate(sc))


@app.get("/api/scenarios/{sid}/results", response_class=JSON)
def results(sid: str):
    return JSON(calculate(_get(sid)))


class CompareBody(BaseModel):
    ids: list[str]


@app.post("/api/compare", response_class=JSON)
def compare_scenarios(body: CompareBody):
    if not body.ids:
        raise HTTPException(400, "Provide at least one scenario id")
    return JSON(compare([_get(i) for i in body.ids]))


# ------------------------------------------------------------------ pricing
@app.get("/api/pricing/providers")
def providers():
    return [{"name": k} for k in PROVIDERS]


@app.get("/api/pricing/{provider}/models", response_class=JSON)
def provider_models(provider: str):
    p = PROVIDERS.get(provider)
    if p is None:
        raise HTTPException(404, "unknown provider")
    return JSON([m.model_dump(mode="json") for m in p.list_models()])


# ------------------------------------------------------------------ model catalog
def _cat(mid: str) -> CatalogModel:
    m = catalog.get(mid)
    if m is None:
        raise HTTPException(404, f"Catalog model '{mid}' not found")
    return m


@app.get("/api/catalog", response_class=JSON)
def catalog_list():
    return JSON([m.model_dump(mode="json") for m in catalog.list()])


@app.post("/api/catalog", response_class=JSON, status_code=201)
def catalog_create(m: CatalogModel):
    if not m.provider.strip() or not m.name.strip():
        raise HTTPException(422, "Provider and model name are required")
    if m.input_price_per_m < 0 or m.output_price_per_m < 0:
        raise HTTPException(422, "Prices cannot be negative")
    return JSON(catalog.create(m).model_dump(mode="json"), status_code=201)


class CatalogUpdate(CatalogModel):
    change_note: str = ""


@app.put("/api/catalog/{mid}", response_class=JSON)
def catalog_update(mid: str, m: CatalogUpdate):
    _cat(mid)
    if m.input_price_per_m < 0 or m.output_price_per_m < 0:
        raise HTTPException(422, "Prices cannot be negative")
    note = m.change_note
    return JSON(catalog.update(mid, CatalogModel(**m.model_dump(exclude={"change_note"})), note).model_dump(mode="json"))


@app.delete("/api/catalog/{mid}")
def catalog_delete(mid: str):
    if not catalog.delete(mid):
        raise HTTPException(404, "not found")
    return {"deleted": mid}


@app.post("/api/catalog/restore", response_class=JSON)
def catalog_restore_all():
    """Restore every published entry to its shipped price; re-adds deleted ones. Your own models are kept."""
    return JSON([m.model_dump(mode="json") for m in catalog.restore()])


@app.post("/api/catalog/{mid}/restore", response_class=JSON)
def catalog_restore_one(mid: str):
    try:
        catalog.restore(mid)
    except KeyError:
        raise HTTPException(404, "Only published (shipped) entries can be restored")
    return JSON(_cat(mid).model_dump(mode="json"))


@app.get("/api/catalog/{mid}/model-config", response_class=JSON)
def catalog_model_config(mid: str):
    """A ready-to-use scenario model built from a catalog entry (prices copied, usage defaults by tier)."""
    return JSON(to_model_config(_cat(mid)).model_dump(mode="json"))


# ------------------------------------------------------------------ import
async def _read(file: UploadFile) -> str:
    raw = await file.read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "File must be UTF-8 text (JSON or CSV)")


def _parse(text: str, filename: str, name: str | None):
    try:
        if filename.lower().endswith(".csv"):
            return parse_csv(text, name or Path(filename).stem)
        return parse_benchmark_json(text)
    except ImportError_ as e:
        raise HTTPException(422, str(e))


@app.post("/api/import/preview", response_class=JSON)
async def import_preview(file: UploadFile = File(...), name: str | None = Form(None)):
    res = _parse(await _read(file), file.filename or "upload.json", name)
    return JSON(res.summary())


@app.post("/api/scenarios/{sid}/import", response_class=JSON)
async def import_into(sid: str, file: UploadFile = File(...), apply_to_inputs: bool = Form(False),
                      name: str | None = Form(None)):
    sc = _get(sid)
    res = _parse(await _read(file), file.filename or "upload.json", name)
    try:
        updated, notes = apply_import(sc, res, apply_to_inputs)
    except ImportError_ as e:
        raise HTTPException(422, str(e))
    saved = store.update(sid, updated)
    return JSON({"scenario": saved.model_dump(mode="json"), "import": res.summary(), "notes": notes})


@app.post("/api/import/scenario", response_class=JSON, status_code=201)
async def import_scenario(file: UploadFile = File(...)):
    try:
        sc = Scenario.model_validate_json(await _read(file))
    except ValidationError as e:
        raise HTTPException(422, f"Not a valid scenario export: {e.errors()[:3]}")
    sc.id = None
    sc.is_sample = False
    return JSON(store.create(sc).model_dump(mode="json"), status_code=201)


# ------------------------------------------------------------------ export
@app.get("/api/scenarios/{sid}/export.json")
def export_json(sid: str):
    sc = _get(sid)
    return Response(sc.model_dump_json(indent=2), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{_slug(sc.name)}.json"'})


@app.get("/api/scenarios/{sid}/results.csv")
def export_csv(sid: str):
    sc = _get(sid)
    res = calculate(sc)
    if not res.get("ok"):
        raise HTTPException(422, "Scenario has validation errors")
    return Response(results_csv(sc.name, res), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{_slug(sc.name)}-results.csv"'})


@app.get("/api/scenarios/{sid}/report", response_class=HTMLResponse)
def report(sid: str):
    sc = _get(sid)
    res = calculate(sc)
    if not res.get("ok"):
        raise HTTPException(422, "Scenario has validation errors")
    return render_report(sc, res)


# ------------------------------------------------------------------ frontend
DIST = Path(os.environ.get("OES_FRONTEND_DIST", Path(__file__).resolve().parents[3] / "frontend" / "dist")).resolve()
print(f"[oes] version {APP_VERSION} · UI folder: {DIST}  (found: {(DIST / 'index.html').is_file()})", flush=True)

MISSING_UI = """<!doctype html><meta charset="utf-8"><title>Outcome Economics Studio</title>
<body style="font:15px/1.5 system-ui,sans-serif;max-width:720px;margin:40px auto;padding:0 16px">
<h2>The API is running, but the UI build was not found</h2>
<p>The server looked for <code>{path}</code>.</p>
<p>Put the pre-built UI there (the folder that contains <code>index.html</code> and <code>assets</code>), or set
<code>OES_FRONTEND_DIST</code> to the folder that does. No restart is needed; refresh this page.</p>
<p>The API itself works: <a href="/api/health">/api/health</a> · <a href="/docs">/docs</a></p></body>"""


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404, "Not Found")
    index = DIST / "index.html"
    if not index.is_file():
        return HTMLResponse(MISSING_UI.format(path=index), status_code=503)
    target = (DIST / path).resolve()
    if path and target.is_file() and DIST in target.parents:
        return FileResponse(target)
    return FileResponse(index)
