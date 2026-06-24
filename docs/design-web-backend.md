# Web Backend Design

## Goals

The Web backend is an operation layer on top of the same core library used by the CLI.
It must not duplicate metadata scanning or fixing rules.

The first Web release provides:

- Track browsing from the long-lived metadata index.
- Single-track tag editing for a small allowlist of fields.
- Background scan jobs.
- Background fix jobs.
- Job status and log inspection.
- Conservative high-confidence watermark cleanup for comment-like metadata fields.

## Non-goals

- No arbitrary shell command execution.
- No full visual frontend yet; FastAPI's OpenAPI UI is the first interface.
- No online metadata lookup in this version.
- No multi-artist write-back rules yet.

## Data Model

The source of truth remains the audio file tag. The index is a cache:

```text
/report/music_metadata_index.csv
```

Single-track edits follow this flow:

```text
validate request
ensure path is under /music
write audio tag
read the file back through mutagen
update the index row
```

Background job state is append-only JSONL:

```text
/report/jobs/jobs.jsonl
/report/jobs/<job_id>.log
/report/jobs/<job_id>_fix_report.csv
```

## API

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
```

`/logs` returns JSON for clients. `/logs.txt` returns `text/plain` for browser-friendly log viewing and supports `tail=N`.

Track IDs are short SHA-256 hashes of the indexed absolute path. They are stable
as long as the mounted path remains stable.

## Safety

- The default Web host is `127.0.0.1`.
- Docker examples must opt into `0.0.0.0`.
- Editable tag fields are allowlisted.
- The backend rejects file paths outside the configured music root.
- Fix jobs are dry-run unless `write=true` is supplied.
- Watermark fixes are scoped to comment-like fields. They must not modify album, title, artist, or albumartist.

## Future Work

- SQLite-backed index for faster pagination and filtering.
- A lightweight Web UI.
- Mapping-table driven fixes.
- Online lookup jobs with rate limiting and source attribution.
- Multi-artist normalization and review workflow.
