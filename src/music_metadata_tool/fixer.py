from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
import csv
import re

from .rules import canonical_genre, normalize_text
from .tags import write_tags


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
    "decision",
    "items",
    "rule_source",
    "skip_reason",
    "old_artist",
    "new_artist",
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


@dataclass
class FixPlan:
    changes: dict[str, str] = field(default_factory=dict)
    decision: str = "unchanged"
    rule_source: str = ""
    skip_reason: str = ""


@dataclass
class AlbumArtistCandidate:
    value: str = ""
    track_count: int = 0
    artist_count: int = 0


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


def albumartist_candidates(rows: list[dict[str, str]]) -> dict[tuple[str, str], AlbumArtistCandidate]:
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
            value, count = next(iter(artists.items()))
            result[key] = AlbumArtistCandidate(value=value, track_count=count, artist_count=len(artists))
    return result


def planned_fix(
    row: dict[str, str],
    items: set[str],
    albumartist_by_album: dict[tuple[str, str], AlbumArtistCandidate],
    fallback_genre: str,
    rules: dict | None = None,
) -> FixPlan:
    plan = FixPlan()
    if "genre" in items:
        old_genre = row.get("genre", "").strip()
        new_genre, genre_status = canonical_genre(old_genre)
        if genre_status in {"invalid_source_noise", "label_or_source_noise"}:
            new_genre = normalize_text(fallback_genre)
        if old_genre != new_genre and genre_status in {"mapped", "invalid_source_noise", "label_or_source_noise"}:
            plan.changes["genre"] = new_genre
            plan.rule_source = plan.rule_source or f"genre.{genre_status}"

    if "albumartist" in items:
        apply_albumartist_rules(row, albumartist_by_album, rules or {}, plan)
    if "compilation_albumartist" in items:
        apply_compilation_albumartist_rules(row, rules or {}, plan)
    if "copy_artist_to_albumartist" in items:
        apply_copy_artist_to_albumartist_rules(row, rules or {}, plan)
    if "infer_artist_from_filename" in items:
        apply_filename_artist_rules(row, rules or {}, plan)
    if "watermark" in items:
        for key in ["comment", "description"]:
            old_value = row.get(key, "").strip()
            if should_clear_watermark_value(old_value):
                plan.changes[key] = ""
                plan.rule_source = plan.rule_source or "watermark.high_confidence"
    if plan.changes:
        plan.decision = "change"
    return plan


def planned_changes(
    row: dict[str, str],
    items: set[str],
    albumartist_by_album: dict[tuple[str, str], AlbumArtistCandidate],
    fallback_genre: str,
    rules: dict | None = None,
) -> dict[str, str]:
    return planned_fix(row, items, albumartist_by_album, fallback_genre, rules).changes


def apply_compilation_albumartist_rules(row: dict[str, str], rules: dict, plan: FixPlan) -> None:
    old_albumartist = row.get("albumartist", "").strip()
    if old_albumartist:
        return
    item_rules = rules.get("compilation_albumartist", {}) if isinstance(rules, dict) else {}
    matched = first_matching_rule(row, item_rules.get("set", []))
    if not matched:
        return
    value = normalize_text(str(matched.get("value", "")))
    if not value:
        return
    plan.changes["albumartist"] = value
    plan.rule_source = plan.rule_source or "compilation_albumartist.set"


def apply_copy_artist_to_albumartist_rules(row: dict[str, str], rules: dict, plan: FixPlan) -> None:
    old_albumartist = row.get("albumartist", "").strip()
    artist = normalize_text(row.get("artist", ""))
    if old_albumartist or not artist:
        return
    item_rules = rules.get("copy_artist_to_albumartist", {}) if isinstance(rules, dict) else {}
    matched = first_matching_rule(row, item_rules.get("copy", []))
    if not matched:
        return
    plan.changes["albumartist"] = artist
    plan.rule_source = plan.rule_source or "copy_artist_to_albumartist.copy"


def apply_filename_artist_rules(row: dict[str, str], rules: dict, plan: FixPlan) -> None:
    item_rules = rules.get("infer_artist_from_filename", {}) if isinstance(rules, dict) else {}
    matched = first_matching_rule(row, item_rules.get("patterns", []))
    if not matched:
        return
    if row.get("artist", "").strip() and row.get("albumartist", "").strip():
        return

    filename = row.get("filename", "")
    pattern = str(matched.get("filename_regex", ""))
    artist_group = str(matched.get("artist_group", "artist"))
    try:
        filename_match = re.search(pattern, filename, re.IGNORECASE)
    except re.error:
        return
    if not filename_match:
        return
    try:
        value = normalize_text(filename_match.group(artist_group))
    except (IndexError, KeyError):
        return
    if not value:
        return

    fields = matched.get("fields", ["artist", "albumartist"])
    if not isinstance(fields, list):
        fields = ["artist", "albumartist"]
    if "artist" in fields and not row.get("artist", "").strip():
        plan.changes["artist"] = value
    if "albumartist" in fields and not row.get("albumartist", "").strip():
        plan.changes["albumartist"] = value
    if plan.changes:
        plan.rule_source = plan.rule_source or "infer_artist_from_filename.patterns"


def apply_albumartist_rules(
    row: dict[str, str],
    albumartist_by_album: dict[tuple[str, str], AlbumArtistCandidate],
    rules: dict,
    plan: FixPlan,
) -> None:
    old_albumartist = row.get("albumartist", "").strip()
    if old_albumartist:
        return
    albumartist_rules = rules.get("albumartist", {}) if isinstance(rules, dict) else {}
    forced = first_matching_rule(row, albumartist_rules.get("force", []))
    if forced:
        value = normalize_text(str(forced.get("value", "")))
        if value:
            plan.changes["albumartist"] = value
            plan.rule_source = "albumartist.force"
            return
    skipped = first_matching_rule(row, albumartist_rules.get("skip", []))
    if skipped:
        plan.decision = "skipped"
        plan.rule_source = "albumartist.skip"
        plan.skip_reason = str(skipped.get("reason", "matched skip rule"))
        return

    key = (row.get("folder", "").strip(), row.get("album", "").strip())
    candidate = albumartist_by_album.get(key)
    if not candidate or not candidate.value:
        return

    defaults = albumartist_rules.get("defaults", {}) if isinstance(albumartist_rules.get("defaults", {}), dict) else {}
    min_album_tracks = int(defaults.get("min_album_tracks", 1))
    max_artist_count = int(defaults.get("max_artist_count", 1))
    if candidate.track_count < min_album_tracks:
        plan.decision = "skipped"
        plan.rule_source = "albumartist.defaults.min_album_tracks"
        plan.skip_reason = f"candidate track count {candidate.track_count} < {min_album_tracks}"
        return
    if candidate.artist_count > max_artist_count:
        plan.decision = "skipped"
        plan.rule_source = "albumartist.defaults.max_artist_count"
        plan.skip_reason = f"candidate artist count {candidate.artist_count} > {max_artist_count}"
        return
    skip_pattern = first_matching_pattern(candidate.value, albumartist_rules.get("skip_patterns", []))
    if skip_pattern:
        plan.decision = "skipped"
        plan.rule_source = "albumartist.skip_patterns"
        plan.skip_reason = f"candidate matched skip pattern: {skip_pattern}"
        return
    allow_patterns = albumartist_rules.get("allow_patterns", [])
    if allow_patterns and not first_matching_pattern(candidate.value, allow_patterns):
        plan.decision = "skipped"
        plan.rule_source = "albumartist.allow_patterns"
        plan.skip_reason = "candidate did not match allow patterns"
        return
    plan.changes["albumartist"] = candidate.value
    plan.rule_source = "albumartist.auto_single_artist_album"


def first_matching_pattern(value: str, patterns) -> str:
    if not isinstance(patterns, list):
        return ""
    for pattern in patterns:
        pattern_text = str(pattern)
        try:
            if re.search(pattern_text, value, re.IGNORECASE):
                return pattern_text
        except re.error:
            continue
    return ""


def first_matching_rule(row: dict[str, str], rules) -> dict | None:
    if not isinstance(rules, list):
        return None
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        match = rule.get("match", {})
        if isinstance(match, dict) and row_matches(row, match):
            return rule
    return None


def row_matches(row: dict[str, str], match: dict[str, str]) -> bool:
    for key, expected in match.items():
        expected_text = str(expected)
        if key.endswith("_regex"):
            row_key = key.removesuffix("_regex")
            try:
                if not re.search(expected_text, row.get(row_key, ""), re.IGNORECASE):
                    return False
            except re.error:
                return False
        elif row.get(key, "") != expected_text:
            return False
    return True


def should_clear_watermark_value(value: str) -> bool:
    normalized = normalize_text(value)
    if not normalized:
        return False
    if normalized.lower() in WATERMARK_CLEAR_VALUES:
        return True
    return any(normalized.startswith(prefix) for prefix in WATERMARK_CLEAR_PREFIXES)


def apply_changes(path: Path, changes: dict[str, str]) -> None:
    write_tags(path, changes)


def run_fix(
    index_path: Path,
    report_path: Path,
    item_names: list[str],
    fallback_genre: str,
    write: bool,
    progress_every: int,
    flush_every: int,
    resume: bool,
    rules: dict | None = None,
) -> None:
    rows = read_index_rows(index_path)
    if resume and report_path.exists() and not report_header_matches(report_path):
        log(f"修复报告字段已变化，将重新生成报告: {report_path}")
        resume = False
    processed_paths = read_processed_paths(report_path) if resume else set()
    items = set(item_names)
    unsupported = items - {
        "genre",
        "albumartist",
        "watermark",
        "compilation_albumartist",
        "copy_artist_to_albumartist",
        "infer_artist_from_filename",
    }
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
            plan = planned_fix(row, items, albumartist_by_album, fallback_genre, rules)
            changes = plan.changes
            report = {
                "path": str(path),
                "status": "unchanged",
                "decision": plan.decision,
                "items": ",".join(sorted(items)),
                "rule_source": plan.rule_source,
                "skip_reason": plan.skip_reason,
                "old_artist": row.get("artist", ""),
                "new_artist": row.get("artist", ""),
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
                if "artist" in changes:
                    report["new_artist"] = changes["artist"]
                    actions.append(f"artist:{row.get('artist', '')!r}->{changes['artist']!r}")
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
            elif plan.decision == "skipped":
                report["status"] = "skipped"
                counts["skipped_by_rule"] += 1
            else:
                counts["unchanged"] += 1
            writer.writerow(report)
            if flush_every > 0 and i % flush_every == 0:
                f.flush()
            if i == 1 or (progress_every > 0 and i % progress_every == 0):
                log(
                    f"修复进度: processed={i:,}, "
                    f"skipped={counts['skipped']:,}, skipped_by_rule={counts['skipped_by_rule']:,}, "
                    f"would_change={counts['would_change']:,}, "
                    f"changed={counts['changed']:,}, errors={counts['errors']:,}"
                )
        f.flush()
    log("修复完成:")
    log(f"- skipped: {counts['skipped']:,}")
    log(f"- skipped_by_rule: {counts['skipped_by_rule']:,}")
    log(f"- unchanged: {counts['unchanged']:,}")
    log(f"- would_change: {counts['would_change']:,}")
    log(f"- changed: {counts['changed']:,}")
    log(f"- errors: {counts['errors']:,}")
