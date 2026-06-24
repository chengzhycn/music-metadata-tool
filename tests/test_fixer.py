from music_metadata_tool.fixer import AlbumArtistCandidate, planned_changes, planned_fix


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


def test_albumartist_inline_skip_pattern_marks_candidate_skipped():
    row = {
        "folder": "/music/Davidson & Davis - Classic Heartstrings",
        "album": "Classic Heartstrings",
        "artist": "天乐唱片",
        "albumartist": "",
    }
    candidates = {
        (row["folder"], row["album"]): AlbumArtistCandidate(value="天乐唱片", track_count=12, artist_count=1)
    }
    rules = {"albumartist": {"skip_patterns": ["唱片"]}}

    plan = planned_fix(row, {"albumartist"}, candidates, "", rules)

    assert plan.changes == {}
    assert plan.decision == "skipped"
    assert plan.rule_source == "albumartist.skip_patterns"
    assert "唱片" in plan.skip_reason


def test_albumartist_inline_force_overrides_auto_candidate():
    row = {
        "folder": "/music/Eason Chan/[Hi-Res]2018 陈奕迅《L.O.V.E.》[Hifitrack]",
        "album": "L.O.V.E.",
        "artist": "陈奕迅 / eason and the duo band",
        "albumartist": "",
    }
    candidates = {
        (row["folder"], row["album"]): AlbumArtistCandidate(
            value="陈奕迅 / eason and the duo band",
            track_count=15,
            artist_count=1,
        )
    }
    rules = {
        "albumartist": {
            "force": [
                {
                    "match": {"folder": row["folder"]},
                    "value": "陈奕迅",
                    "reason": "album artist should be Eason Chan",
                }
            ]
        }
    }

    plan = planned_fix(row, {"albumartist"}, candidates, "", rules)

    assert plan.changes == {"albumartist": "陈奕迅"}
    assert plan.rule_source == "albumartist.force"
