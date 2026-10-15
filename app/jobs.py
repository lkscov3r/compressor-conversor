"""Fila simples de tarefas em memória, executadas em threads."""

from __future__ import annotations

import re
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import image, video

JOB_TTL_SECONDS = 2 * 60 * 60  # arquivos de tarefas antigas são apagados após 2 horas
_JOB_DIR_RE = re.compile(r"[0-9a-f]{32}")


@dataclass
class Job:
    id: str
    kind: str  # "video" ou "image"
    operation: str  # "compress" ou "convert"
    original_name: str
    input_path: Path
    output_path: Path
    target_format: str
    level: str
    codec: str
    lossless: bool
    status: str = "na_fila"  # na_fila, processando, concluido, erro
    progress: float = 0.0
    error: str | None = None
    input_size: int = 0
    output_size: int | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    @property
    def download_name(self) -> str:
        stem = Path(self.original_name).stem or "arquivo"
        suffix = "comprimido" if self.operation == "compress" else "convertido"
        return f"{stem}_{suffix}.{self.target_format}"

    def public(self) -> dict:
        data = asdict(self)
        for key in ("input_path", "output_path"):
            data.pop(key)
        data["download_name"] = self.download_name
        if self.output_size and self.input_size:
            data["reduction"] = 1 - self.output_size / self.input_size
        return data


class JobManager:
    def __init__(self, data_dir: Path, workers: int = 2):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=workers)
        self._remove_leftovers()

    def _remove_leftovers(self) -> None:
        """Apaga pastas de tarefas de execuções anteriores do app."""
        for path in self.data_dir.iterdir():
            if path.is_dir() and _JOB_DIR_RE.fullmatch(path.name):
                shutil.rmtree(path, ignore_errors=True)

    def new_job_dir(self) -> tuple[str, Path]:
        job_id = uuid.uuid4().hex
        job_dir = self.data_dir / job_id
        job_dir.mkdir(parents=True)
        return job_id, job_dir

    def submit(self, job: Job) -> Job:
        self.cleanup()
        job.input_size = job.input_path.stat().st_size
        with self.lock:
            self.jobs[job.id] = job
        self.executor.submit(self._run, job)
        return job

    def get(self, job_id: str) -> Job | None:
        with self.lock:
            return self.jobs.get(job_id)

    def delete(self, job_id: str) -> None:
        with self.lock:
            job = self.jobs.pop(job_id, None)
        if job:
            shutil.rmtree(job.input_path.parent, ignore_errors=True)

    def cleanup(self) -> None:
        now = time.time()
        with self.lock:
            expired = [j.id for j in self.jobs.values()
                       if j.finished_at and now - j.finished_at > JOB_TTL_SECONDS]
        for job_id in expired:
            self.delete(job_id)

    def _run(self, job: Job) -> None:
        job.status = "processando"
        try:
            if job.kind == "image":
                image.process_image(job.input_path, job.output_path, job.target_format,
                                    level=job.level, lossless=job.lossless)
            else:
                self._run_video(job)
            job.output_size = job.output_path.stat().st_size
            job.progress = 1.0
            job.status = "concluido"
        except Exception as exc:  # noqa: BLE001 - qualquer falha vira mensagem para o usuário
            job.status = "erro"
            job.error = str(exc) or exc.__class__.__name__
            job.output_path.unlink(missing_ok=True)
        finally:
            job.finished_at = time.time()
            job.input_path.unlink(missing_ok=True)

    def _run_video(self, job: Job) -> None:
        info = video.probe(job.input_path)

        def on_progress(value: float) -> None:
            job.progress = value

        if job.operation == "compress":
            args = video.build_compress_command(job.input_path, job.output_path, info,
                                                job.codec, job.level)
        else:
            args = video.build_convert_command(job.input_path, job.output_path, info,
                                               job.target_format, job.level)
        video.run_ffmpeg(args, info.duration, on_progress)
