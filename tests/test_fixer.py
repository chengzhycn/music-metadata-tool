from music_metadata_tool.fixer import planned_changes


def test_watermark_fix_only_clears_comment_and_description():
    row = {
        "album": "彭佳慧:绝对收藏",
        "comment": "捌零音樂論壇/賴子收藏",
        "description": "kuwo",
    }

    changes = planned_changes(row, {"watermark"}, {}, "")

    assert changes == {"comment": "", "description": ""}
    assert "album" not in changes


def test_watermark_fix_leaves_normal_comment_alone():
    row = {
        "comment": "现场录音版本",
        "description": "",
    }

    assert planned_changes(row, {"watermark"}, {}, "") == {}
