from __future__ import annotations

from collections import Counter
from pathlib import Path
import csv
import os
import tempfile

from .tags import INDEX_FIELDS, is_audio_file, read_metadata_row, utc_now


MULTI_ARTIST_RE = __import__("re").compile(r"feat\.|ft\.|featuring|&|/|、|,|，|\+", __import__("re").IGNORECASE)


def log(message: str = "") -> None:
    print(message, flush=True)


def iter_audio_files(root: Path):
    for dirpath, _, filenames in os.walk(root):
        for filename in sorted(filenames):
            path = Path(dirpath) / filename
            if is_audio_file(path):
                yield path


def read_index(index_path: Path) -> dict[str, dict[str, str]]:
    if not index_path.exists():
        return {}
    with index_path.open(encoding="utf-8-sig", newline="") as f:
        return {row["path"]: row for row in csv.DictReader(f) if row.get("path")}


def unchanged(existing: dict[str, str], path: Path) -> bool:
    stat = path.stat()
    return (
        existing.get("status") == "active"
        and existing.get("size") == str(stat.st_size)
        and existing.get("mtime_ns") == str(stat.st_mtime_ns)
    )


def write_counter(path: Path, counter: Counter, key_name: str) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[key_name, "count"])
        writer.writeheader()
        for key, count in counter.most_common():
            writer.writerow({key_name: key, "count": count})


def export_reports(index_path: Path, report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "missing_albumartist": report_dir / "missing_albumartist.csv",
        "multi_artist": report_dir / "multi_artist_suspect.csv",
        "watermark": report_dir / "watermark_suspect.csv",
        "errors": report_dir / "read_errors.csv",
        "deleted": report_dir / "deleted_files.csv",
    }
    genre_counter = Counter()
    artist_counter = Counter()
    albumartist_counter = Counter()
    counts = Counter()

    with index_path.open(encoding="utf-8-sig", newline="") as index_f, \
        files["missing_albumartist"].open("w", encoding="utf-8-sig", newline="") as missing_f, \
        files["multi_artist"].open("w", encoding="utf-8-sig", newline="") as multi_f, \
        files["watermark"].open("w", encoding="utf-8-sig", newline="") as watermark_f, \
        files["errors"].open("w", encoding="utf-8-sig", newline="") as errors_f, \
        files["deleted"].open("w", encoding="utf-8-sig", newline="") as deleted_f:
        reader = csv.DictReader(index_f)
        writers = {
            "missing_albumartist": csv.DictWriter(missing_f, fieldnames=INDEX_FIELDS),
            "multi_artist": csv.DictWriter(multi_f, fieldnames=INDEX_FIELDS),
            "watermark": csv.DictWriter(watermark_f, fieldnames=INDEX_FIELDS),
            "errors": csv.DictWriter(errors_f, fieldnames=INDEX_FIELDS),
            "deleted": csv.DictWriter(deleted_f, fieldnames=INDEX_FIELDS),
        }
        for writer in writers.values():
            writer.writeheader()
        for row in reader:
            counts["total"] += 1
            if row.get("status") == "deleted":
                counts["deleted"] += 1
                writers["deleted"].writerow(row)
                continue
            counts["active"] += 1
            genre_counter[row.get("genre", "")] += 1
            artist_counter[row.get("artist", "")] += 1
            albumartist_counter[row.get("albumartist", "")] += 1
            if not row.get("albumartist", "").strip():
                counts["missing_albumartist"] += 1
                writers["missing_albumartist"].writerow(row)
            if MULTI_ARTIST_RE.search(row.get("artist", "")):
                counts["multi_artist"] += 1
                writers["multi_artist"].writerow(row)
            if row.get("watermark_text", "").strip():
                counts["watermark"] += 1
                writers["watermark"].writerow(row)
            if row.get("error", "").strip():
                counts["errors"] += 1
                writers["errors"].writerow(row)

    write_counter(report_dir / "genre_stats.csv", genre_counter, "genre")
    write_counter(report_dir / "artist_stats.csv", artist_counter, "artist")
    write_counter(report_dir / "albumartist_stats.csv", albumartist_counter, "albumartist")
    log("报表已生成:")
    log(f"- {report_dir / 'genre_stats.csv'}")
    log(f"- {files['missing_albumartist']}")
    log(f"- {files['watermark']}")
    log("统计摘要:")
    for key in ["total", "active", "deleted", "missing_albumartist", "multi_artist", "watermark", "errors"]:
        log(f"- {key}: {counts[key]:,}")


def scan_library(
    music_dir: Path,
    index_path: Path,
    report_dir: Path,
    full: bool,
    progress_every: int,
) -> None:
    music_dir = music_dir.resolve()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    old_index = {} if full else read_index(index_path)
    seen_paths = set()
    counts = Counter()

    log(f"扫描目录: {music_dir}")
    log(f"索引文件: {index_path}")
    log(f"模式: {'full' if full else 'incremental'}")

    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8-sig",
        newline="",
        dir=index_path.parent,
        delete=False,
        prefix=f".{index_path.name}.",
    ) as tmp_f:
        tmp_path = Path(tmp_f.name)
        writer = csv.DictWriter(tmp_f, fieldnames=INDEX_FIELDS)
        writer.writeheader()
        for path in iter_audio_files(music_dir):
            path_str = str(path)
            seen_paths.add(path_str)
            existing = old_index.get(path_str)
            if existing and unchanged(existing, path):
                writer.writerow(existing)
                counts["unchanged"] += 1
            else:
                writer.writerow(read_metadata_row(path))
                counts["scanned"] += 1
            counts["found"] += 1
            if counts["found"] == 1 or (progress_every > 0 and counts["found"] % progress_every == 0):
                log(
                    "扫描进度: "
                    f"found={counts['found']:,}, scanned={counts['scanned']:,}, "
                    f"unchanged={counts['unchanged']:,}, current={path.name}"
                )

        for path_str, row in old_index.items():
            if path_str in seen_paths:
                continue
            deleted = {field: row.get(field, "") for field in INDEX_FIELDS}
            deleted["status"] = "deleted"
            deleted["scan_time"] = utc_now()
            writer.writerow(deleted)
            counts["deleted"] += 1

    tmp_path.replace(index_path)
    log(
        "扫描完成: "
        f"found={counts['found']:,}, scanned={counts['scanned']:,}, "
        f"unchanged={counts['unchanged']:,}, deleted={counts['deleted']:,}"
    )
    export_reports(index_path, report_dir)
