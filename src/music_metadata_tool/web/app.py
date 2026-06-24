from __future__ import annotations

from pathlib import Path
import csv
import hashlib

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from .. import __version__
from ..tags import INDEX_FIELDS, read_metadata_row, write_tags
from .jobs import JobManager


EDITABLE_TAGS = {"title", "artist", "albumartist", "album", "date", "genre", "composer", "comment"}


class TagUpdate(BaseModel):
    tags: dict[str, str] = Field(default_factory=dict)


class ScanJobRequest(BaseModel):
    full: bool = False
    progress_every: int = 100


class FixJobRequest(BaseModel):
    items: list[str] = Field(default_factory=lambda: ["genre", "albumartist"])
    fallback_genre: str = ""
    write: bool = False
    progress_every: int = 100
    flush_every: int = 1000
    resume: bool = True


def path_id(path: str) -> str:
    return hashlib.sha256(path.encode("utf-8")).hexdigest()[:24]


def safe_resolve_under(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    root_resolved = root.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise HTTPException(status_code=400, detail="path is outside music directory")
    return resolved


def read_index_rows(index_path: Path) -> list[dict[str, str]]:
    if not index_path.exists():
        return []
    with index_path.open(encoding="utf-8-sig", newline="") as f:
        rows = []
        for row in csv.DictReader(f):
            row["id"] = path_id(row.get("path", ""))
            rows.append(row)
        return rows


def rewrite_index_row(index_path: Path, updated_row: dict[str, str]) -> None:
    rows = read_index_rows(index_path)
    updated_path = updated_row["path"]
    found = False
    with index_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=INDEX_FIELDS)
        writer.writeheader()
        for row in rows:
            clean = {field: row.get(field, "") for field in INDEX_FIELDS}
            if clean["path"] == updated_path:
                clean = {field: updated_row.get(field, "") for field in INDEX_FIELDS}
                found = True
            writer.writerow(clean)
        if not found:
            writer.writerow({field: updated_row.get(field, "") for field in INDEX_FIELDS})


def create_app(music_dir: Path, index_path: Path, report_dir: Path) -> FastAPI:
    music_dir = music_dir.resolve()
    index_path = index_path.resolve()
    report_dir = report_dir.resolve()
    manager = JobManager(report_dir)
    app = FastAPI(title="music-metadata-tool", version=__version__)

    @app.get("/api/health")
    def health():
        return {
            "ok": True,
            "music_dir": str(music_dir),
            "index_path": str(index_path),
            "report_dir": str(report_dir),
            "index_exists": index_path.exists(),
        }

    @app.get("/api/tracks")
    def tracks(
        page: int = Query(1, ge=1),
        page_size: int = Query(100, ge=1, le=500),
        q: str = "",
        artist: str = "",
        album: str = "",
        status: str = "",
        genre_empty: bool = False,
        watermark: bool = False,
    ):
        rows = read_index_rows(index_path)
        filtered = []
        q_lower = q.lower()
        for row in rows:
            if status and row.get("status") != status:
                continue
            if artist and artist.lower() not in row.get("artist", "").lower():
                continue
            if album and album.lower() not in row.get("album", "").lower():
                continue
            if genre_empty and row.get("genre", "").strip():
                continue
            if watermark and not row.get("watermark_text", "").strip():
                continue
            if q_lower:
                haystack = " ".join(
                    row.get(key, "")
                    for key in ["title", "artist", "albumartist", "album", "genre", "filename", "path"]
                ).lower()
                if q_lower not in haystack:
                    continue
            filtered.append(row)
        start = (page - 1) * page_size
        end = start + page_size
        return {"total": len(filtered), "page": page, "page_size": page_size, "items": filtered[start:end]}

    @app.get("/api/tracks/{track_id}")
    def track(track_id: str):
        for row in read_index_rows(index_path):
            if row["id"] == track_id:
                return row
        raise HTTPException(status_code=404, detail="track not found")

    @app.patch("/api/tracks/{track_id}/tags")
    def update_tags(track_id: str, update: TagUpdate):
        bad = set(update.tags) - EDITABLE_TAGS
        if bad:
            raise HTTPException(status_code=400, detail=f"unsupported tag(s): {', '.join(sorted(bad))}")
        target = None
        for row in read_index_rows(index_path):
            if row["id"] == track_id:
                target = row
                break
        if not target:
            raise HTTPException(status_code=404, detail="track not found")
        path = safe_resolve_under(Path(target["path"]), music_dir)
        write_tags(path, update.tags)
        fresh = read_metadata_row(path)
        rewrite_index_row(index_path, fresh)
        fresh["id"] = path_id(fresh["path"])
        return fresh

    @app.post("/api/jobs/scan")
    def start_scan(request: ScanJobRequest):
        return manager.submit_scan(music_dir, index_path, report_dir, request.full, request.progress_every)

    @app.post("/api/jobs/fix")
    def start_fix(request: FixJobRequest):
        return manager.submit_fix(
            index_path,
            request.items,
            request.fallback_genre,
            request.write,
            request.progress_every,
            request.flush_every,
            request.resume,
        )

    @app.get("/api/jobs")
    def jobs():
        return {"items": manager.list_jobs()}

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str):
        item = manager.get_job(job_id)
        if item is None:
            raise HTTPException(status_code=404, detail="job not found")
        return item

    @app.get("/api/jobs/{job_id}/logs")
    def job_logs(job_id: str):
        text = manager.get_log(job_id)
        if text is None:
            raise HTTPException(status_code=404, detail="job not found")
        return {"job_id": job_id, "log": text}

    @app.get("/api/jobs/{job_id}/logs.txt", response_class=PlainTextResponse)
    def job_logs_text(job_id: str, tail: int = Query(0, ge=0, le=10000)):
        text = manager.get_log(job_id)
        if text is None:
            raise HTTPException(status_code=404, detail="job not found")
        if tail:
            lines = text.splitlines()
            text = "\n".join(lines[-tail:])
            if text:
                text += "\n"
        return PlainTextResponse(text, media_type="text/plain; charset=utf-8")

    return app
