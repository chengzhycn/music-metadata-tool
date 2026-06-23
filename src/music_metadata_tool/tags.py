from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re

from mutagen import File


AUDIO_EXTS = {
    ".mp3",
    ".flac",
    ".m4a",
    ".aac",
    ".ogg",
    ".opus",
    ".wav",
    ".wma",
    ".ape",
}

METADATA_FIELDS = [
    "title",
    "artist",
    "albumartist",
    "album",
    "date",
    "tracknumber",
    "discnumber",
    "genre",
    "composer",
    "comment",
    "description",
    "grouping",
    "organization",
    "publisher",
    "label",
    "copyright",
    "encoder",
    "raw_tag_keys",
    "watermark_text",
    "error",
]

INDEX_FIELDS = [
    "path",
    "folder",
    "filename",
    "ext",
    "size",
    "mtime_ns",
    "mtime_iso",
    "scan_time",
    "status",
    *METADATA_FIELDS,
]

EXTRA_TAG_ALIASES = {
    "comment": {"comment", "comments", "comm", "©cmt"},
    "description": {"description", "desc", "ldes", "©des"},
    "grouping": {"grouping", "contentgroup", "tit1", "©grp"},
    "organization": {"organization", "organisation", "tpub", "publisher"},
    "publisher": {"publisher", "organization", "organisation", "tpub"},
    "label": {"label", "organization", "organisation", "publisher", "record label"},
    "copyright": {"copyright", "tcop", "cprt", "©cpy"},
    "encoder": {"encodedby", "encoded by", "encoder", "tenc", "tool", "encoding"},
}

WATERMARK_RE = re.compile(
    r"(pt80|www\.|kuwo|撕零|賴子|赖子|論壇|论坛|收藏|压制|壓制|download|uploaded)",
    re.IGNORECASE,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def is_audio_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in AUDIO_EXTS


def text_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        values = [text_value(v) for v in value]
        return "; ".join(v for v in values if v)
    if hasattr(value, "text"):
        return text_value(value.text)
    if hasattr(value, "url"):
        return str(value.url)
    return str(value)


def join_tag(audio, key: str) -> str:
    if audio is None:
        return ""
    values = audio.get(key, [])
    if values is None:
        return ""
    return text_value(values)


def raw_tag_map(audio) -> dict[str, str]:
    if audio is None or audio.tags is None or not hasattr(audio.tags, "items"):
        return {}
    result = {}
    for key, value in audio.tags.items():
        value_text = text_value(value).strip()
        if value_text:
            result[str(key)] = value_text
    return result


def normalized_key(key: str) -> str:
    return key.lower().split(":", 1)[0].strip()


def raw_lookup(raw_tags: dict[str, str], logical_key: str) -> str:
    aliases = EXTRA_TAG_ALIASES[logical_key]
    values = []
    for key, value in raw_tags.items():
        if normalized_key(key) in aliases:
            values.append(value)
    return "; ".join(dict.fromkeys(values))


def detect_watermark(raw_tags: dict[str, str]) -> str:
    hits = []
    for key, value in raw_tags.items():
        if WATERMARK_RE.search(value):
            hits.append(f"{key}={value}")
    return " | ".join(hits)


def filesystem_row(path: Path, status: str = "active") -> dict[str, str]:
    stat = path.stat()
    mtime = datetime.fromtimestamp(stat.st_mtime, timezone.utc).replace(microsecond=0)
    row = {field: "" for field in INDEX_FIELDS}
    row.update(
        {
            "path": str(path),
            "folder": str(path.parent),
            "filename": path.name,
            "ext": path.suffix.lower(),
            "size": str(stat.st_size),
            "mtime_ns": str(stat.st_mtime_ns),
            "mtime_iso": mtime.isoformat(),
            "scan_time": utc_now(),
            "status": status,
        }
    )
    return row


def read_metadata_row(path: Path) -> dict[str, str]:
    row = filesystem_row(path)
    try:
        audio_easy = File(path, easy=True)
        audio_raw = File(path, easy=False)
        if audio_easy is None and audio_raw is None:
            row["error"] = "mutagen cannot read"
            return row

        raw_tags = raw_tag_map(audio_raw)
        easy_comment = join_tag(audio_easy, "comment")
        raw_comment = raw_lookup(raw_tags, "comment")
        row.update(
            {
                "title": join_tag(audio_easy, "title"),
                "artist": join_tag(audio_easy, "artist"),
                "albumartist": join_tag(audio_easy, "albumartist"),
                "album": join_tag(audio_easy, "album"),
                "date": join_tag(audio_easy, "date"),
                "tracknumber": join_tag(audio_easy, "tracknumber"),
                "discnumber": join_tag(audio_easy, "discnumber"),
                "genre": join_tag(audio_easy, "genre"),
                "composer": join_tag(audio_easy, "composer"),
                "comment": easy_comment or raw_comment,
                "description": raw_lookup(raw_tags, "description"),
                "grouping": join_tag(audio_easy, "grouping") or raw_lookup(raw_tags, "grouping"),
                "organization": raw_lookup(raw_tags, "organization"),
                "publisher": raw_lookup(raw_tags, "publisher"),
                "label": raw_lookup(raw_tags, "label"),
                "copyright": raw_lookup(raw_tags, "copyright"),
                "encoder": raw_lookup(raw_tags, "encoder"),
                "raw_tag_keys": "; ".join(sorted(raw_tags.keys())),
                "watermark_text": detect_watermark(raw_tags),
            }
        )
        return row
    except Exception as exc:
        row["error"] = str(exc)
        return row


def open_easy(path: Path):
    audio = File(path, easy=True)
    if audio is None:
        raise ValueError("mutagen cannot read")
    if audio.tags is None:
        audio.add_tags()
    return audio


def first_tag(audio, key: str) -> str:
    values = audio.get(key, [])
    if isinstance(values, str):
        return values.strip()
    if values:
        return str(values[0]).strip()
    return ""


def set_tag(audio, key: str, value: str) -> None:
    if value:
        audio[key] = [value]
    elif key in audio:
        del audio[key]


def write_tags(path: Path, updates: dict[str, str]) -> None:
    audio = open_easy(path)
    for key, value in updates.items():
        set_tag(audio, key, value)
    audio.save()
