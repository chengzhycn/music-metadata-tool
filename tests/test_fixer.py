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


def test_compilation_albumartist_sets_various_artists_by_rule():
    row = {
        "folder": "/music/乐队的夏天/第1期",
        "album": "乐队的夏天 第1期",
        "artist": "新裤子",
        "albumartist": "",
    }
    rules = {
        "compilation_albumartist": {
            "set": [
                {
                    "match": {"folder_regex": "乐队的夏天"},
                    "value": "Various Artists",
                }
            ]
        }
    }

    plan = planned_fix(row, {"compilation_albumartist"}, {}, "", rules)

    assert plan.changes == {"albumartist": "Various Artists"}
    assert plan.rule_source == "compilation_albumartist.set"


def test_copy_artist_to_albumartist_by_rule():
    row = {
        "folder": "/music/音乐/2024年QQ音乐巅峰榜单",
        "filename": "APT.-ROSÉ&Bruno Mars.flac",
        "artist": "ROSÉ; Bruno Mars",
        "albumartist": "",
    }
    rules = {
        "copy_artist_to_albumartist": {
            "copy": [
                {
                    "match": {"folder_regex": "QQ音乐巅峰榜单"},
                    "reason": "chart singles should keep artist and albumartist aligned",
                }
            ]
        }
    }

    plan = planned_fix(row, {"copy_artist_to_albumartist"}, {}, "", rules)

    assert plan.changes == {"albumartist": "ROSÉ; Bruno Mars"}
    assert plan.rule_source == "copy_artist_to_albumartist.copy"


def test_copy_artist_to_albumartist_ignores_empty_artist():
    row = {
        "folder": "/music/音乐/2024年QQ音乐巅峰榜单",
        "filename": "unknown.flac",
        "artist": "",
        "albumartist": "",
    }
    rules = {
        "copy_artist_to_albumartist": {
            "copy": [{"match": {"folder_regex": "QQ音乐巅峰榜单"}}]
        }
    }

    plan = planned_fix(row, {"copy_artist_to_albumartist"}, {}, "", rules)

    assert plan.changes == {}


def test_infer_artist_from_filename_does_not_change_album():
    row = {
        "folder": "/music/Eason Chan/陈奕迅 WAV",
        "filename": "01. 陈奕迅 - 24.wav",
        "artist": "",
        "albumartist": "",
        "album": "",
    }
    rules = {
        "infer_artist_from_filename": {
            "patterns": [
                {
                    "match": {"folder_regex": "Eason Chan|陈奕迅"},
                    "filename_regex": r"^\d+\.\s*(?P<artist>.+?)\s+-\s+.+\.[^.]+$",
                    "artist_group": "artist",
                    "fields": ["artist", "albumartist"],
                }
            ]
        }
    }

    plan = planned_fix(row, {"infer_artist_from_filename"}, {}, "", rules)

    assert plan.changes == {"artist": "陈奕迅", "albumartist": "陈奕迅"}
    assert "album" not in plan.changes
    assert plan.rule_source == "infer_artist_from_filename.patterns"


def test_set_fields_sets_album_by_rule():
    row = {
        "folder": "/music/Davidson & Davis - Classic Heartstrings",
        "album": "classic heaststsings",
        "artist": "Davidson & Davis",
        "albumartist": "Davidson & Davis",
    }
    rules = {
        "set_fields": {
            "set": [
                {
                    "match": {"folder": row["folder"]},
                    "values": {"album": "Heartstrings"},
                }
            ]
        }
    }

    plan = planned_fix(row, {"set_fields"}, {}, "", rules)

    assert plan.changes == {"album": "Heartstrings"}
    assert plan.rule_source == "set_fields.set"


def test_clear_fields_clears_explicit_watermark_values_only():
    row = {
        "description": "酷我音乐",
        "organization": "PMEDIA",
        "publisher": "Real Publisher",
        "artist": "Beyoncé",
    }
    rules = {
        "clear_fields": {
            "clear": [
                {"fields": ["description"], "value_regex": "^酷我音乐$"},
                {"fields": ["organization", "publisher"], "value_regex": "^PMEDIA$"},
            ]
        }
    }

    plan = planned_fix(row, {"clear_fields"}, {}, "", rules)

    assert plan.changes == {"description": "", "organization": ""}
    assert "publisher" not in plan.changes
    assert "artist" not in plan.changes
    assert plan.rule_source == "clear_fields.clear"


def test_split_artist_splits_artist_without_changing_albumartist():
    row = {
        "folder": "/music/MUSIC/中文音乐/张雨生",
        "artist": "张雨生&张惠妹",
        "albumartist": "张雨生",
    }
    rules = {
        "split_artist": {
            "rules": [
                {
                    "match": {"folder_regex": "/music/MUSIC/中文音乐/"},
                    "separator_regex": r"\s*(?:&|/|、|，|,|\+)\s*",
                }
            ]
        }
    }

    plan = planned_fix(row, {"split_artist"}, {}, "", rules)

    assert plan.changes == {"artist": ["张雨生", "张惠妹"]}
    assert "albumartist" not in plan.changes
    assert plan.rule_source == "split_artist.rules"


def test_split_artist_can_skip_known_group_names():
    row = {
        "folder": "/music/MUSIC/中文音乐/林忆莲",
        "artist": "林忆莲 & Blue Jeans",
    }
    rules = {
        "split_artist": {
            "skip_patterns": ["Blue Jeans"],
            "rules": [{"match": {"folder_regex": "/music/MUSIC/中文音乐/"}}],
        }
    }

    plan = planned_fix(row, {"split_artist"}, {}, "", rules)

    assert plan.changes == {}
    assert plan.decision == "skipped"
    assert plan.rule_source == "split_artist.skip_patterns"
