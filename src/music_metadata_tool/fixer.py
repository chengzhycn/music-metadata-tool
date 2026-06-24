from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import csv

from .rules import canonical_genre, normalize_text
from .tags import open_easy, set_tag


WATERMARK_CLEAR_VALUES = {
    "kuwo",
    "pmedia",
    "www.t.me/pmedia_music",
    "捌零音樂論壇/賴子收藏",
}

WATERMARK_CLEAR_PREFIXES = (
    "This music track is downloaded from qobuz",
    "Uploaded By ",
)

FIX_REPORT_FIELDS = [
    "path",
    "status",
    "items",
    "old_genre",
    "new_genre",
    "old_albumartist",
    "new_albumartist",
    "old_comment",
    "new_comment",
    "old_description",
    "new_description",
    "actions",
    "error",
]


def log(message: str = "") -> None:
    print(message, flush=True)


def read_index_rows(index_path: Path) -> list[dict[str, str]]:
    with index_path.open(encoding="utf-8-sig", newline="") as f:
        return [row for row in csv.DictReader(f) if row.get("status") != "deleted"]


def read_processed_paths(report_path: Path) -> set[str]:
    if not report_path.exists():
        return set()
    processed = set()
    with report_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("status") != "error" and row.get("path"):
                processed.add(row["path"])
    return processed


def report_header_matches(report_path: Path) -> bool:
    if not report_path.exists():
        return True
    with report_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return True
    return header == FIX_REPORT_FIELDS


def albumartist_candidates(rows: list[dict[str, str]]) -> dict[tuple[str, str], str]:
    grouped = defaultdict(Counter)
    for row in rows:
        album = row.get("album", "").strip()
        folder = row.get("folder", "").strip()
        artist = row.get("artist", "").strip()
        if album and artist:
            grouped[(folder, album)][artist] += 1
    result = {}
    for key, artists in grouped.items():
        if len(artists) == 1:
            result[key] = next(iter(artists))
    return result


def planned_changes(
    row: dict[str, str],
    items: set[str],
    albumartist_by_album: dict[tuple[str, str], str],
    fallback_genre: str,
) -> dict[str, str]:
    changes = {}
    if "genre" in items:
        old_genre = row.get("genre", "").strip()
        new_genre, genre_status = canonical_genre(old_genre)
        if genre_status in {"invalid_source_noise", "label_or_source_noise"}:
            new_genre = normalize_text(fallback_genre)
        if old_genre != new_genre and genre_status in {"mapped", "invalid_source_noise", "label_or_source_noise"}:
            changes["genre"] = new_genre

    if "albumartist" in items:
        old_albumartist = row.get("albumartist", "").strip()
        key = (row.get("folder", "").strip(), row.get("album", "").strip())
        candidate = albumartist_by_album.get(key, "")
        if not old_albumartist and candidate:
            changes["albumartist"] = candidate
    if "watermark" in items:
        for key in ["comment", "description"]:
            old_value = row.get(key, "").strip()
            if should_clear_watermark_value(old_value):
                changes[key] = ""
    return changes


def should_clear_watermark_value(value: str) -> bool:
    normalized = normalize_text(value)
    if not normalized:
        return False
    if normalized.lower() in WATERMARK_CLEAR_VALUES:
        return True
    return any(normalized.startswith(prefix) for prefix in WATERMARK_CLEAR_PREFIXES)


def apply_changes(path: Path, changes: dict[str, str]) -> None:
    audio = open_easy(path)
    for key, value in changes.items():
        set_tag(audio, key, value)
    audio.save()


def run_fix(
    index_path: Path,
    report_path: Path,
    item_names: list[str],
    fallback_genre: str,
    write: bool,
    progress_every: int,
    flush_every: int,
    resume: bool,
) -> None:
    rows = read_index_rows(index_path)
    if resume and report_path.exists() and not report_header_matches(report_path):
        log(f"修复报告字段已变化，将重新生成报告: {report_path}")
        resume = False
    processed_paths = read_processed_paths(report_path) if resume else set()
    items = set(item_names)
    unsupported = items - {"genre", "albumartist", "watermark"}
    if unsupported:
        raise ValueError(f"unsupported fix item(s): {', '.join(sorted(unsupported))}")

    albumartist_by_album = albumartist_candidates(rows)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    counts = Counter()
    mode = "WRITE" if write else "DRY-RUN"
    log(f"修复模式: {mode}")
    log(f"修复项目: {', '.join(sorted(items))}")
    log(f"索引文件: {index_path}")
    log(f"报告文件: {report_path}")
    if processed_paths:
        log(f"发现修复断点，已处理 {len(processed_paths):,} 个文件，将跳过")

    write_header = not (resume and report_path.exists())
    with report_path.open("a" if resume else "w", encoding="utf-8-sig" if write_header else "utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIX_REPORT_FIELDS)
        if write_header:
            writer.writeheader()
        for i, row in enumerate(rows, start=1):
            path = Path(row["path"])
            if str(path) in processed_paths:
                counts["skipped"] += 1
                continue
            changes = planned_changes(row, items, albumartist_by_album, fallback_genre)
            report = {
                "path": str(path),
                "status": "unchanged",
                "items": ",".join(sorted(items)),
                "old_genre": row.get("genre", ""),
                "new_genre": row.get("genre", ""),
                "old_albumartist": row.get("albumartist", ""),
                "new_albumartist": row.get("albumartist", ""),
                "old_comment": row.get("comment", ""),
                "new_comment": row.get("comment", ""),
                "old_description": row.get("description", ""),
                "new_description": row.get("description", ""),
                "actions": "",
                "error": "",
            }
            if changes:
                actions = []
                if "genre" in changes:
                    report["new_genre"] = changes["genre"]
                    actions.append(f"genre:{row.get('genre', '')!r}->{changes['genre']!r}")
                if "albumartist" in changes:
                    report["new_albumartist"] = changes["albumartist"]
                    actions.append(f"albumartist:{row.get('albumartist', '')!r}->{changes['albumartist']!r}")
                if "comment" in changes:
                    report["new_comment"] = changes["comment"]
                    actions.append(f"comment:{row.get('comment', '')!r}->{changes['comment']!r}")
                if "description" in changes:
                    report["new_description"] = changes["description"]
                    actions.append(f"description:{row.get('description', '')!r}->{changes['description']!r}")
                report["actions"] = "; ".join(actions)
                if write:
                    try:
                        apply_changes(path, changes)
                        report["status"] = "changed"
                        counts["changed"] += 1
                    except Exception as exc:
                        report["status"] = "error"
                        report["error"] = str(exc)
                        counts["errors"] += 1
                else:
                    report["status"] = "would_change"
                    counts["would_change"] += 1
            else:
                counts["unchanged"] += 1
            writer.writerow(report)
            if flush_every > 0 and i % flush_every == 0:
                f.flush()
            if i == 1 or (progress_every > 0 and i % progress_every == 0):
                log(
                    f"修复进度: processed={i:,}, "
                    f"skipped={counts['skipped']:,}, would_change={counts['would_change']:,}, "
                    f"changed={counts['changed']:,}, errors={counts['errors']:,}"
                )
        f.flush()
    log("修复完成:")
    log(f"- skipped: {counts['skipped']:,}")
    log(f"- unchanged: {counts['unchanged']:,}")
    log(f"- would_change: {counts['would_change']:,}")
    log(f"- changed: {counts['changed']:,}")
    log(f"- errors: {counts['errors']:,}")
