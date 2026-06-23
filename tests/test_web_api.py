from __future__ import annotations

import csv
from pathlib import Path

from fastapi.testclient import TestClient

from music_metadata_tool.tags import INDEX_FIELDS
from music_metadata_tool.web.app import create_app, path_id


def write_index(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=INDEX_FIELDS)
        writer.writeheader()
        for row in rows:
            payload = {field: "" for field in INDEX_FIELDS}
            payload.update(row)
            writer.writerow(payload)


def test_tracks_filters_and_pagination(tmp_path: Path):
    music_dir = tmp_path / "music"
    report_dir = tmp_path / "report"
    music_dir.mkdir()
    first = music_dir / "a.flac"
    second = music_dir / "b.flac"
    first.write_bytes(b"fake")
    second.write_bytes(b"fake")
    index = report_dir / "music_metadata_index.csv"
    write_index(
        index,
        [
            {
                "path": str(first),
                "folder": str(music_dir),
                "filename": "a.flac",
                "status": "active",
                "title": "信封",
                "artist": "李志",
                "album": "被禁忌的游戏",
                "genre": "",
            },
            {
                "path": str(second),
                "folder": str(music_dir),
                "filename": "b.flac",
                "status": "active",
                "title": "Other",
                "artist": "Other Artist",
                "album": "Other Album",
                "genre": "rock",
                "watermark_text": "COMMENT=www.pt80.net",
            },
        ],
    )

    client = TestClient(create_app(music_dir, index, report_dir))
    response = client.get("/api/tracks", params={"artist": "李志", "genre_empty": True})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["title"] == "信封"

    response = client.get("/api/tracks", params={"watermark": True})
    assert response.status_code == 200
    assert response.json()["total"] == 1


def test_track_lookup_by_id(tmp_path: Path):
    music_dir = tmp_path / "music"
    report_dir = tmp_path / "report"
    music_dir.mkdir()
    track = music_dir / "a.flac"
    track.write_bytes(b"fake")
    index = report_dir / "music_metadata_index.csv"
    write_index(index, [{"path": str(track), "folder": str(music_dir), "filename": "a.flac", "status": "active"}])

    client = TestClient(create_app(music_dir, index, report_dir))
    response = client.get(f"/api/tracks/{path_id(str(track))}")
    assert response.status_code == 200
    assert response.json()["path"] == str(track)


def test_scan_job_creation(tmp_path: Path):
    music_dir = tmp_path / "music"
    report_dir = tmp_path / "report"
    music_dir.mkdir()
    index = report_dir / "music_metadata_index.csv"
    client = TestClient(create_app(music_dir, index, report_dir))

    response = client.post("/api/jobs/scan", json={"full": False, "progress_every": 1})
    assert response.status_code == 200
    job = response.json()
    assert job["kind"] == "scan"
    assert job["status"] in {"pending", "running", "completed"}


def test_update_rejects_unsupported_tags(tmp_path: Path):
    music_dir = tmp_path / "music"
    report_dir = tmp_path / "report"
    music_dir.mkdir()
    track = music_dir / "a.flac"
    track.write_bytes(b"fake")
    index = report_dir / "music_metadata_index.csv"
    write_index(index, [{"path": str(track), "folder": str(music_dir), "filename": "a.flac", "status": "active"}])
    client = TestClient(create_app(music_dir, index, report_dir))

    response = client.patch(f"/api/tracks/{path_id(str(track))}/tags", json={"tags": {"path": "/etc/passwd"}})
    assert response.status_code == 400
