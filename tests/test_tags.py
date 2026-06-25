from pathlib import Path
import wave

from music_metadata_tool.tags import detect_watermark, read_metadata_row, write_tags


def test_detect_watermark_ignores_album_and_lyrics_false_positives():
    raw_tags = {
        "album": "彭佳慧:绝对收藏",
        "lyrics": "爱一个人不是收藏一个恶性循环",
    }

    assert detect_watermark(raw_tags) == ""


def test_detect_watermark_uses_comment_like_source_fields():
    raw_tags = {
        "comment": "捌零音樂論壇/賴子收藏",
        "description": "kuwo",
        "wwwaudiosource": "www.t.me/pmedia_music",
    }

    watermark = detect_watermark(raw_tags)

    assert "comment=捌零音樂論壇/賴子收藏" in watermark
    assert "description=kuwo" in watermark
    assert "wwwaudiosource=www.t.me/pmedia_music" in watermark


def create_silent_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(44100)
        wav.writeframes(b"\x00\x00" * 44100)


def test_write_and_read_wav_id3_tags(tmp_path: Path):
    path = tmp_path / "01. 陈奕迅 - 测试.wav"
    create_silent_wav(path)

    write_tags(
        path,
        {
            "title": "测试",
            "artist": "陈奕迅",
            "albumartist": "陈奕迅",
            "album": "测试专辑",
        },
    )

    row = read_metadata_row(path)

    assert row["title"] == "测试"
    assert row["artist"] == "陈奕迅"
    assert row["albumartist"] == "陈奕迅"
    assert row["album"] == "测试专辑"
    assert "TPE1" in row["raw_tag_keys"]
    assert "TPE2" in row["raw_tag_keys"]


def test_write_and_read_wav_multi_value_artist(tmp_path: Path):
    path = tmp_path / "合唱.wav"
    create_silent_wav(path)

    write_tags(path, {"artist": ["张雨生", "张惠妹"]})

    row = read_metadata_row(path)

    assert row["artist"] == "张雨生; 张惠妹"
