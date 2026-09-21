from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from uuid import UUID, uuid4
from threading import Lock

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


app = FastAPI(title="App Store Review Analysis", version="0.1.0")
DATA_DIR = get_settings().data_dir
logger = logging.getLogger(__name__)
NLP_LOCK = Lock()
STATIC_DIR = Path(__file__).resolve().parent / "static"

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
    return {"status": "ok"}


def _read_collection(collection_id):
    folder = DATA_DIR / str(collection_id)
    try:
        return json.loads((folder / "analysis.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise HTTPException(404, "Collection not found") from None
    except (OSError, ValueError):
        logger.exception("Could not read collection %s", collection_id)
        raise HTTPException(500, "Could not read saved collection") from None


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
            temp = folder / (filename + ".tmp")
            temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
            temp.replace(folder / filename)
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


@app.post("/collections/{collection_id}/analyze")
def analyze_collection(collection_id: UUID):
    if not NLP_LOCK.acquire(blocking=False):
        raise HTTPException(409, "An NLP analysis is already running; retry after it finishes")
    try:
        analysis = _read_collection(collection_id)
        folder = DATA_DIR / str(collection_id)
        raw = json.loads((folder / "raw.json").read_text(encoding="utf-8"))
        from bootstrap import get_review_analysis
        analysis["insights"] = get_review_analysis().analyze(raw)
        files = create_visualizations(analysis, folder,
                                      get_settings().visualization_topic_limit)
        analysis["visualizations"] = {
            name: f"/collections/{collection_id}/visualizations/{filename}"
            for name, filename in files.items()
        }
        temp = folder / "analysis.json.tmp"
        temp.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(folder / "analysis.json")
        return analysis
    except HTTPException:
        raise
    except (OSError, ValueError, RuntimeError, ImportError):
        logger.exception("NLP analysis failed for %s", collection_id)
        raise HTTPException(500, "NLP analysis failed; check server logs. Previous results are preserved") from None
    finally:
        NLP_LOCK.release()


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
