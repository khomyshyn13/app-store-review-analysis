from datetime import datetime, timezone
from contextlib import asynccontextmanager
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import logging
from pathlib import Path
from threading import Lock
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from collection.collector import CollectionError, collect_reviews, search_apps
from analytics.metrics import calculate_metrics
from analytics.reporting import render_report
from analytics.visualizations import create_visualizations
from processing.preprocessing import preprocess_reviews
from config.settings import get_settings


DATA_DIR = get_settings().data_dir
logger = logging.getLogger(__name__)
ANALYSIS_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="analysis")
JOB_LOCK = Lock()
STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(application):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for path in DATA_DIR.glob("*/analysis.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("job", {}).get("status") in {"queued", "running"}:
                value["job"] = {"status": "failed", "progress": 100,
                                "stage": "Analysis interrupted by service restart",
                                "message": "Start the analysis again"}
                _write_json(path, value)
        except (OSError, ValueError):
            logger.warning("Could not recover job state at %s", path)
    application.state.model_status = "disabled"
    if get_settings().warmup_models:
        application.state.model_status = "loading"
        try:
            from bootstrap import get_review_analysis
            await asyncio.to_thread(get_review_analysis().warmup)
            application.state.model_status = "ready"
        except Exception:
            application.state.model_status = "failed"
            logger.exception("Model warmup failed")
    yield
    ANALYSIS_EXECUTOR.shutdown(wait=False, cancel_futures=False)


app = FastAPI(title="App Store Review Analysis", version="0.2.0", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class CollectionRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    app_name: str = Field(min_length=1, max_length=200)
    country: str = Field(default="us", pattern=r"^[a-zA-Z]{2}$")
    count: int = Field(default=100, ge=1, le=500, strict=True)
    seed: int = Field(default=42, strict=True)
    max_pages: int = Field(default=10, ge=1, le=10, strict=True)
    app_id: str | None = Field(default=None, pattern=r"^[0-9]+$")


@app.get("/", include_in_schema=False)
def frontend():
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html")


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok", "models": app.state.model_status,
            "storage": str(DATA_DIR)}


def _write_json(path, payload):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _read_collection(collection_id):
    folder = DATA_DIR / str(collection_id)
    try:
        return json.loads((folder / "analysis.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise HTTPException(404, "Collection not found") from None
    except (OSError, ValueError):
        logger.exception("Could not read collection %s", collection_id)
        raise HTTPException(500, "Could not read saved collection") from None


@app.get("/collections")
def list_collections(limit: int = Query(default=50, ge=1, le=200)):
    items = []
    if not DATA_DIR.exists():
        return {"collections": items}
    for path in DATA_DIR.glob("*/analysis.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            items.append({key: value.get(key) for key in (
                "collection_id", "app_name", "developer", "country", "collected_at", "collected_count"
            )} | {"analysis_status": value.get("job", {}).get("status")
                  or value.get("insights", {}).get("status", "not_run")})
        except (OSError, ValueError):
            logger.warning("Skipping unreadable collection at %s", path)
    items.sort(key=lambda item: item.get("collected_at") or "", reverse=True)
    return {"collections": items[:limit]}


@app.get("/apps/search")
def find_apps(name: str = Query(min_length=1, max_length=200),
              country: str = Query(default="us", pattern=r"^[a-zA-Z]{2}$")):
    """Find app names, developers and IDs in a storefront."""
    try:
        return {"apps": search_apps(name, country)}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except CollectionError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/collections", status_code=201)
def create_collection(request: CollectionRequest, response: Response):
    try:
        candidates = search_apps(request.app_name, request.country)
        if request.app_id is not None:
            matches = [item for item in candidates if item["id"] == request.app_id]
            if not matches:
                raise HTTPException(422, "Selected app_id is not in the search results")
        else:
            matches = [item for item in candidates
                       if item["name"].strip().casefold() == request.app_name.casefold()]
        if len(matches) != 1:
            raise HTTPException(409, {
                "message": "Select an app and repeat the request with its app_id",
                "candidates": candidates,
            })
        selected = matches[0]
        raw = collect_reviews(selected["id"], request.country, request.count,
                              request.seed, request.max_pages)
        raw.update(app_name=selected["name"], developer=selected["developer"],
                   collected_at=datetime.now(timezone.utc).isoformat())
        prepared = preprocess_reviews(raw)
        collection_id = str(uuid4())
        metadata = {key: value for key, value in raw.items() if key != "reviews"}
        analysis = {
            "collection_id": collection_id,
            **metadata,
            "preprocessing": prepared["preprocessing"],
            "metrics": calculate_metrics(raw),
            "insights": {"status": "not_run", "data": None},
            "download_url": f"/collections/{collection_id}/reviews/download",
        }
        folder = DATA_DIR / collection_id
        folder.mkdir(parents=True)
        files = create_visualizations(analysis, folder,
                                      get_settings().visualization_topic_limit)
        analysis["visualizations"] = {
            name: f"/collections/{collection_id}/visualizations/{filename}"
            for name, filename in files.items()
        }
        for filename, payload in (("raw.json", raw), ("prepared.json", prepared),
                                  ("analysis.json", analysis)):
            _write_json(folder / filename, payload)
        response.headers["Location"] = f"/collections/{collection_id}"
        return analysis
    except CollectionError as exc:
        raise HTTPException(502, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except OSError:
        logger.exception("Could not save collection")
        raise HTTPException(500, "Could not save collection") from None


@app.get("/collections/{collection_id}")
def get_collection(collection_id: UUID):
    return _read_collection(collection_id)


def _run_analysis(collection_id):
    folder = DATA_DIR / str(collection_id)
    try:
        analysis = _read_collection(collection_id)
        analysis["job"] = {"status": "running", "progress": 15, "stage": "Loading saved reviews"}
        _write_json(folder / "analysis.json", analysis)
        raw = json.loads((folder / "raw.json").read_text(encoding="utf-8"))
        from bootstrap import get_review_analysis
        analysis["job"] = {"status": "running", "progress": 30, "stage": "Analyzing sentiment and topics"}
        _write_json(folder / "analysis.json", analysis)
        analysis["insights"] = get_review_analysis().analyze(raw)
        analysis["job"] = {"status": "running", "progress": 90, "stage": "Creating visualizations"}
        _write_json(folder / "analysis.json", analysis)
        files = create_visualizations(analysis, folder,
                                      get_settings().visualization_topic_limit)
        analysis["visualizations"] = {
            name: f"/collections/{collection_id}/visualizations/{filename}"
            for name, filename in files.items()
        }
        analysis["job"] = {"status": "completed", "progress": 100, "stage": "Analysis complete",
                           "finished_at": datetime.now(timezone.utc).isoformat()}
        _write_json(folder / "analysis.json", analysis)
    except Exception:
        logger.exception("NLP analysis failed for %s", collection_id)
        try:
            analysis = _read_collection(collection_id)
            analysis["job"] = {"status": "failed", "progress": 100,
                               "stage": "Analysis failed", "message": "Check server logs and try again"}
            _write_json(folder / "analysis.json", analysis)
        except Exception:
            logger.exception("Could not persist failure status for %s", collection_id)


@app.post("/collections/{collection_id}/analyze", status_code=202)
def analyze_collection(collection_id: UUID, response: Response):
    with JOB_LOCK:
        analysis = _read_collection(collection_id)
        if analysis.get("job", {}).get("status") in {"queued", "running"}:
            response.headers["Location"] = f"/collections/{collection_id}/analysis-status"
            return analysis["job"]
        job = {"status": "queued", "progress": 0, "stage": "Waiting for analysis worker",
               "started_at": datetime.now(timezone.utc).isoformat()}
        analysis["job"] = job
        _write_json(DATA_DIR / str(collection_id) / "analysis.json", analysis)
        ANALYSIS_EXECUTOR.submit(_run_analysis, collection_id)
    response.headers["Location"] = f"/collections/{collection_id}/analysis-status"
    return job


@app.get("/collections/{collection_id}/analysis-status")
def analysis_status(collection_id: UUID):
    analysis = _read_collection(collection_id)
    return analysis.get("job", {"status": "not_started", "progress": 0,
                                "stage": "Analysis has not been started"})


@app.get("/collections/{collection_id}/reviews/download")
def download_reviews(collection_id: UUID):
    _read_collection(collection_id)
    path = DATA_DIR / str(collection_id) / "raw.json"
    if not path.is_file():
        raise HTTPException(500, "Saved raw reviews are unavailable")
    return FileResponse(path, media_type="application/json",
                        filename=f"reviews-{collection_id}.json")


@app.get("/collections/{collection_id}/report/download")
def download_report(collection_id: UUID):
    report = render_report(_read_collection(collection_id))
    return Response(report, media_type="text/markdown",
                    headers={"Content-Disposition": f'attachment; filename="report-{collection_id}.md"'})


@app.get("/collections/{collection_id}/visualizations/{filename}")
def download_visualization(collection_id: UUID, filename: str):
    allowed = {"rating_distribution.png", "sentiment_distribution.png", "top_issues.png"}
    if filename not in allowed:
        raise HTTPException(404, "Visualization not found")
    _read_collection(collection_id)
    path = DATA_DIR / str(collection_id) / filename
    if not path.is_file():
        raise HTTPException(404, "Visualization not available for this collection")
    return FileResponse(path, media_type="image/png", filename=filename)
