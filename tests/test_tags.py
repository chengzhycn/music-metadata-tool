from music_metadata_tool.tags import detect_watermark


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
