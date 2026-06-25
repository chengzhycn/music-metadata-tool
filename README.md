# music-metadata-tool

长期维护的音乐库元数据索引、检查和修复工具。

项目目标是把音乐文件 tags 当作真实来源，把索引和报表当作可重建缓存。CLI 和 Web API 共用同一套核心逻辑，避免出现“命令行一套规则、Web 一套规则”的分裂。

## 功能

- `scan`: 构建或增量更新音乐元数据索引。
- `fix`: 根据索引执行保守 tag 修复，默认 dry-run。
- `web`: 启动 REST API 后端，通过 Swagger UI 查看和操作。

当前 `fix` 第一版支持：

- `genre`: 清理明显噪声，归一常见 genre 别名。
- `albumartist`: 对单艺术家专辑补齐空的 albumartist。
- `watermark`: 清理高置信水印备注，目前只会计划修改 `comment` 和 `description`，不会修改 `album`、`title`、`artist` 等核心元数据字段。
- `compilation_albumartist`: 通过本次任务传入的规则，把合辑/综艺类目录的空 albumartist 填成指定值，例如 `Various Artists`。
- `infer_artist_from_filename`: 通过本次任务传入的文件名规则，从文件名推断并填充空的 `artist` / `albumartist`；不会自动修改 `album`。

WAV 文件使用 Mutagen 的 WAVE/ID3 写入路径，`artist`、`albumartist` 等字段会写成 WAV 内嵌 ID3 frame，并在扫描时从这些 frame 读回。

## 数据文件

默认建议挂载：

```text
/music   音乐库目录
/report  索引、报表、任务日志目录
```

主要文件：

```text
/report/music_metadata_index.csv
/report/genre_stats.csv
/report/artist_stats.csv
/report/albumartist_stats.csv
/report/missing_albumartist.csv
/report/multi_artist_suspect.csv
/report/watermark_suspect.csv
/report/read_errors.csv
/report/jobs/jobs.jsonl
/report/jobs/<job_id>.log
```

## 扫描

增量扫描：

```bash
music-metadata-tool scan /music \
  --index /report/music_metadata_index.csv \
  --report-dir /report
```

强制全量重建：

```bash
music-metadata-tool scan /music \
  --index /report/music_metadata_index.csv \
  --report-dir /report \
  --full
```

索引用 `path + size + mtime_ns` 判断文件是否发生变化。增量扫描时：

- 新文件读取 tags 并加入索引。
- 未变化文件复用旧索引行。
- 已变化文件重新读取 tags。
- 不存在的旧文件标记为 `deleted`。

## 修复

Dry-run：

```bash
music-metadata-tool fix \
  --index /report/music_metadata_index.csv \
  --report /report/fix_report.csv \
  --items genre,albumartist
```

写入：

```bash
music-metadata-tool fix \
  --index /report/music_metadata_index.csv \
  --report /report/fix_report.csv \
  --items genre,albumartist \
  --write
```

清理高置信备注水印：

```bash
music-metadata-tool fix \
  --index /report/music_metadata_index.csv \
  --report /report/fix_watermark_report.csv \
  --items watermark \
  --write
```

`watermark` 修复项只处理 `comment` 和 `description` 中的高置信脏值，例如 `kuwo`、`捌零音樂論壇/賴子收藏`、`This music track is downloaded from qobuz`。扫描阶段发现的 `album=绝对收藏`、歌词里出现“收藏”等情况不应作为水印修复目标。

Web fix job 支持一次性 inline rules。规则会直接参与本次任务执行，并保存到 `/report/jobs/<job_id>_request.json` 作为审计快照：

```json
{
  "items": ["albumartist"],
  "write": false,
  "resume": false,
  "rules": {
    "albumartist": {
      "skip_patterns": ["唱片", "/", "、", "&", "feat\\."],
      "allow_patterns": ["^[^/、&,，+]+$"],
      "force": [
        {
          "match": {
            "folder": "/music/Eason Chan/[Hi-Res]2018 陈奕迅《L.O.V.E.》[Hifitrack]"
          },
          "value": "陈奕迅",
          "reason": "album artist should be Eason Chan"
        }
      ],
      "skip": [
        {
          "match": {
            "folder": "/music/Davidson & Davis - Classic Heartstrings"
          },
          "reason": "artist tag is label/source name"
        }
      ]
    }
  }
}
```

合辑和文件名推断规则示例：

```json
{
  "items": ["compilation_albumartist", "infer_artist_from_filename"],
  "write": false,
  "resume": false,
  "rules": {
    "compilation_albumartist": {
      "set": [
        {
          "match": {
            "folder_regex": "乐队的夏天|综艺纯享音乐|披荆斩棘|我们的歌"
          },
          "value": "Various Artists"
        }
      ]
    },
    "infer_artist_from_filename": {
      "patterns": [
        {
          "match": {
            "folder_regex": "Eason Chan|陈奕迅"
          },
          "filename_regex": "^\\d+\\.\\s*(?P<artist>.+?)\\s+-\\s+.+\\.[^.]+$",
          "artist_group": "artist",
          "fields": ["artist", "albumartist"]
        }
      ]
    }
  }
}
```

如果噪声 genre 需要指定替代值：

```bash
music-metadata-tool fix \
  --index /report/music_metadata_index.csv \
  --items genre \
  --fallback-genre folk \
  --write
```

`fix_report.csv` 同时也是修复断点文件。默认会 resume：如果中途重启，下一次会跳过报告中已经成功处理过的文件。每 1000 个处理项 flush 一次，可通过 `--flush-every` 调整。

## Web 后端

启动：

```bash
music-metadata-tool web \
  --music-dir /music \
  --index /report/music_metadata_index.csv \
  --report-dir /report \
  --host 0.0.0.0 \
  --port 8080
```

Swagger UI：

```text
http://localhost:8080/docs
```

主要 API：

```text
GET    /api/health
GET    /api/tracks
GET    /api/tracks/{track_id}
PATCH  /api/tracks/{track_id}/tags
POST   /api/jobs/scan
POST   /api/jobs/fix
GET    /api/jobs
GET    /api/jobs/{job_id}
GET    /api/jobs/{job_id}/logs
GET    /api/jobs/{job_id}/logs.txt
GET    /api/jobs/{job_id}/report
GET    /api/jobs/{job_id}/request
```

浏览器里查看日志建议用纯文本接口：

```text
http://localhost:8080/api/jobs/<job_id>/logs.txt?tail=200
```

`tail=200` 表示只看最后 200 行。旧的 `/logs` 接口返回 JSON，适合程序调用。

下载 fix dry-run 或写入任务生成的 CSV 报告：

```text
http://localhost:8080/api/jobs/<job_id>/report
```

查看任务请求参数快照：

```text
http://localhost:8080/api/jobs/<job_id>/request
```

Web 写 tag 时会：

```text
校验字段 -> 确认路径在 /music 内 -> 写入音频文件 -> 重新读取该文件 -> 更新索引行
```

## Docker

构建：

```bash
docker build -t music-metadata-tool:local .
```

默认 Docker 构建使用清华 PyPI 镜像。需要切回官方源时：

```bash
docker build \
  --build-arg PIP_INDEX_URL=https://pypi.org/simple \
  -t music-metadata-tool:local .
```

扫描：

```bash
docker run --rm \
  -v "/path/to/music:/music" \
  -v "$PWD/report:/report" \
  music-metadata-tool:local \
  scan /music --index /report/music_metadata_index.csv --report-dir /report
```

Web：

```bash
docker run --rm \
  -p 8080:8080 \
  -v "/path/to/music:/music" \
  -v "$PWD/report:/report" \
  music-metadata-tool:local \
  web --music-dir /music --index /report/music_metadata_index.csv --report-dir /report --host 0.0.0.0 --port 8080
```

## 安全边界

- Web 默认监听 `127.0.0.1`，Docker 暴露给外部时需要显式传 `--host 0.0.0.0`。
- Web API 不接受任意 shell 命令。
- 单曲编辑只允许修改白名单 tag。
- 文件路径必须位于配置的音乐库目录下。
- 修复任务默认 dry-run，只有 `write=true` 或 CLI `--write` 才写入音频文件。
- 自动水印修复不修改专辑名、曲名、艺术家、专辑艺术家等核心字段。

## 开发

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest
```

设计文档：

```text
docs/design-web-backend.md
```
