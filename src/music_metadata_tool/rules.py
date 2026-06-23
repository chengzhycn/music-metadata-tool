from __future__ import annotations

import re
import unicodedata


INVALID_GENRE_RE = re.compile(r"(www\.|\.net$|kuwo|^\d{5,}_\d+$)", re.I)
LABEL_OR_SOURCE_GENRES = {"华纳音乐"}

GENRE_ALIASES = {
    "pop": {"pop", "pop music"},
    "chinese pop": {
        "c-pop",
        "cpop",
        "c pop",
        "china-pop",
        "china pop",
        "chinese pop",
        "mandopop",
        "国语流行乐",
        "国语流行",
        "流行",
        "流行音乐",
        "流行歌曲",
        "流行曲",
        "流行乐",
        "pop,mandopop",
        "pop,mandopop,chinese",
    },
    "cantopop": {"cantopop", "广东歌/香港流行乐", "pop,rock,hong.kong"},
    "j-pop": {"jpop", "j-pop", "j", "ポップ"},
    "k-pop": {"k-pop", "kpop", "trot"},
    "rock": {"rock", "rock music", "rock & pop", "pop&rock", "pop, rock", "pop/rock", "pop-rock", "pop rock"},
    "folk": {"folk", "pop-folk", "folk/rock", "singer/songwriter", "唱作歌手"},
    "hip-hop/rap": {"hip-hop/rap", "hip-hop", "rap"},
    "r&b/soul": {"r&b", "r&b/soul", "rhythm & blues / soul", "soul", "灵魂乐"},
    "soundtrack": {"soundtrack", "原声音乐", "原声配乐", "game", "drama"},
}


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", (value or "").strip())
    value = value.replace("→", ">")
    value = re.sub(r"\s+", " ", value)
    return value


def canonical_genre(value: str) -> tuple[str, str]:
    raw = normalize_text(value)
    if not raw:
        return "", "missing"
    key = raw.lower()
    if INVALID_GENRE_RE.search(key):
        return "", "invalid_source_noise"
    if raw in LABEL_OR_SOURCE_GENRES:
        return "", "label_or_source_noise"
    for canonical, aliases in GENRE_ALIASES.items():
        if key in aliases:
            return canonical, "mapped"
    return raw, "unmapped_review"
