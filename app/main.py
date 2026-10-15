"""Servidor local: API + interface web."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import image, video
from .jobs import Job, JobManager

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("COMPRESSOR_DATA_DIR", BASE_DIR.parent / "dados"))

LEVELS = {"alta", "equilibrada", "maxima"}
CODECS = {"h264", "h265", "av1"}

app = FastAPI(title="Compressor e Conversor")
manager = JobManager(DATA_DIR)


def _extension(filename: str) -> str:
    return Path(filename).suffix.lower().lstrip(".")


def _kind_for(ext: str) -> str | None:
    if ext in image.IMAGE_INPUT_EXTENSIONS:
        return "image"
    if ext in video.VIDEO_INPUT_EXTENSIONS:
        return "video"
    return None


@app.get("/api/info")
def info() -> dict:
    return {
        "ffmpeg": video.ffmpeg_available(),
        "video": {"input": sorted(video.VIDEO_INPUT_EXTENSIONS), "output": video.VIDEO_FORMATS},
        "image": {"input": sorted(image.IMAGE_INPUT_EXTENSIONS), "output": list(image.IMAGE_FORMATS)},
        "levels": ["alta", "equilibrada", "maxima"],
        "codecs": ["h264", "h265", "av1"],
    }


@app.post("/api/jobs")
def create_job(
    file: UploadFile = File(...),
    operation: str = Form("compress"),
    target_format: str = Form(""),
    level: str = Form("alta"),
    codec: str = Form("h265"),
    lossless: bool = Form(False),
) -> dict:
    ext = _extension(file.filename or "")
    kind = _kind_for(ext)
    if kind is None:
        raise HTTPException(400, f"Formato de arquivo não suportado: .{ext or '?'}")
    if operation not in ("compress", "convert"):
        raise HTTPException(400, "Operação inválida.")
    if level not in LEVELS:
        raise HTTPException(400, "Nível de compressão inválido.")
    if codec not in CODECS:
        raise HTTPException(400, "Codec inválido.")
    if kind == "video" and not video.ffmpeg_available():
        raise HTTPException(503, "FFmpeg não encontrado. Instale-o para processar vídeos (veja o README).")

    if kind == "image":
        source_ext = image.normalize_extension(ext)
        if operation == "compress":
            # BMP não tem compressão útil: comprime para PNG (sem perdas).
            target = "png" if source_ext == "bmp" else source_ext
        else:
            target = image.normalize_extension(target_format)
            if target not in image.IMAGE_FORMATS:
                raise HTTPException(400, "Formato de imagem de destino inválido.")
    else:
        if operation == "compress":
            target = "mp4"
        else:
            target = target_format.lower()
            if target not in video.VIDEO_FORMATS:
                raise HTTPException(400, "Formato de vídeo de destino inválido.")

    job_id, job_dir = manager.new_job_dir()
    input_path = job_dir / f"entrada.{ext}"
    with input_path.open("wb") as out:
        shutil.copyfileobj(file.file, out, length=1024 * 1024)

    job = Job(
        id=job_id, kind=kind, operation=operation, original_name=file.filename or "arquivo",
        input_path=input_path, output_path=job_dir / f"saida.{target}",
        target_format=target, level=level, codec=codec, lossless=lossless,
    )
    return manager.submit(job).public()


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = manager.get(job_id)
    if job is None:
        raise HTTPException(404, "Tarefa não encontrada.")
    return job.public()


@app.get("/api/jobs/{job_id}/download")
def download(job_id: str) -> FileResponse:
    job = manager.get(job_id)
    if job is None or job.status != "concluido":
        raise HTTPException(404, "Arquivo não disponível.")
    return FileResponse(job.output_path, filename=job.download_name)


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str) -> dict:
    manager.delete(job_id)
    return {"ok": True}


app.mount("/", StaticFiles(directory=BASE_DIR / "static", html=True), name="static")
