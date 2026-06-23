from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import contextlib
import io
import json
import threading
import uuid

from ..fixer import run_fix
from ..indexer import scan_library


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class JobRecord:
    id: str
    kind: str
    status: str
    created_at: str
    updated_at: str
    log_path: str
    error: str = ""


class Tee(io.TextIOBase):
    def __init__(self, *streams):
        self.streams = streams

    def write(self, text: str) -> int:
        for stream in self.streams:
            stream.write(text)
            stream.flush()
        return len(text)

    def flush(self) -> None:
        for stream in self.streams:
            stream.flush()


class JobManager:
    def __init__(self, report_dir: Path, max_workers: int = 1):
        self.report_dir = report_dir
        self.jobs_dir = report_dir / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_file = self.jobs_dir / "jobs.jsonl"
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.lock = threading.Lock()
        self.jobs: dict[str, JobRecord] = {}
        self._load_jobs()

    def _load_jobs(self) -> None:
        if not self.jobs_file.exists():
            return
        with self.jobs_file.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                data = json.loads(line)
                self.jobs[data["id"]] = JobRecord(**data)

    def _append_job(self, job: JobRecord) -> None:
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        with self.jobs_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(job), ensure_ascii=False) + "\n")

    def _update(self, job_id: str, **updates) -> None:
        with self.lock:
            job = self.jobs[job_id]
            for key, value in updates.items():
                setattr(job, key, value)
            job.updated_at = now_iso()
            self._append_job(job)

    def list_jobs(self) -> list[dict]:
        return [asdict(job) for job in sorted(self.jobs.values(), key=lambda item: item.created_at, reverse=True)]

    def get_job(self, job_id: str) -> dict | None:
        job = self.jobs.get(job_id)
        return asdict(job) if job else None

    def get_log(self, job_id: str) -> str | None:
        job = self.jobs.get(job_id)
        if not job:
            return None
        path = Path(job.log_path)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")

    def submit_scan(self, music_dir: Path, index_path: Path, report_dir: Path, full: bool, progress_every: int) -> dict:
        return self._submit("scan", lambda: scan_library(music_dir, index_path, report_dir, full, progress_every))

    def submit_fix(
        self,
        index_path: Path,
        items: list[str],
        fallback_genre: str,
        write: bool,
        progress_every: int,
        flush_every: int,
        resume: bool,
    ) -> dict:
        job_id = uuid.uuid4().hex
        report_path = self.jobs_dir / f"{job_id}_fix_report.csv"
        return self._submit(
            "fix",
            lambda: run_fix(
                index_path,
                report_path,
                items,
                fallback_genre,
                write,
                progress_every,
                flush_every,
                resume,
            ),
            job_id=job_id,
        )

    def _submit(self, kind: str, fn, job_id: str | None = None) -> dict:
        job_id = job_id or uuid.uuid4().hex
        log_path = self.jobs_dir / f"{job_id}.log"
        job = JobRecord(
            id=job_id,
            kind=kind,
            status="pending",
            created_at=now_iso(),
            updated_at=now_iso(),
            log_path=str(log_path),
        )
        with self.lock:
            self.jobs[job_id] = job
            self._append_job(job)
        self.executor.submit(self._run, job_id, fn)
        return asdict(job)

    def _run(self, job_id: str, fn) -> None:
        job = self.jobs[job_id]
        self._update(job_id, status="running")
        log_path = Path(job.log_path)
        try:
            with log_path.open("a", encoding="utf-8") as log_f, \
                contextlib.redirect_stdout(Tee(log_f)), \
                contextlib.redirect_stderr(Tee(log_f)):
                fn()
            self._update(job_id, status="completed")
        except Exception as exc:
            with log_path.open("a", encoding="utf-8") as log_f:
                log_f.write(f"\nERROR: {exc}\n")
            self._update(job_id, status="failed", error=str(exc))
