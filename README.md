# music-metadata-tool

长期维护的音乐元数据索引与修复工具。

## 功能

- `scan`: 构建或增量更新音乐元数据索引。
- `fix`: 根据索引执行保守 tag 修复，默认 dry-run。

当前 `fix` 第一版支持：

- `genre`: 清理明显噪声，归一常见 genre 别名。
- `albumartist`: 对单艺术家专辑补齐空的 albumartist。

## 构建/增量扫描

```bash
music-metadata-tool scan /music --index /report/music_metadata_index.csv --report-dir /report
```

强制全量重建：

```bash
music-metadata-tool scan /music --index /report/music_metadata_index.csv --report-dir /report --full
```

## Dry-run 修复

```bash
music-metadata-tool fix --index /report/music_metadata_index.csv --report /report/fix_report.csv --items genre,albumartist
```

`fix_report.csv` 同时也是修复断点文件。默认会 resume：如果中途重启，下一次会跳过报告中已经成功处理过的文件。每 1000 个处理项 flush 一次，可通过 `--flush-every` 调整。

## 写入修复

```bash
music-metadata-tool fix --index /report/music_metadata_index.csv --report /report/fix_report.csv --items genre,albumartist --write
```

如果噪声 genre 需要指定替代值：

```bash
music-metadata-tool fix --index /report/music_metadata_index.csv --items genre --fallback-genre folk --write
```

## Docker

```bash
docker build -t music-metadata-tool:local .
docker run --rm \
  -v "/path/to/music:/music" \
  -v "$PWD/report:/report" \
  music-metadata-tool:local \
  scan /music --index /report/music_metadata_index.csv --report-dir /report
```

## 索引原则

索引用 `path + size + mtime_ns` 判断文件是否发生变化。增量扫描时：

- 新文件读取 tags 并加入索引。
- 未变化文件复用旧索引行。
- 已变化文件重新读取 tags。
- 不存在的旧文件标记为 `deleted`。

修复命令写入 tag 后，文件 mtime 会变化；下一次 `scan` 会自动刷新这些文件的索引。
