"""Compressão e conversão de vídeos com FFmpeg."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

VIDEO_FORMATS = ["mp4", "mkv", "webm", "mov", "avi", "gif"]
VIDEO_INPUT_EXTENSIONS = {"mp4", "m4v", "mkv", "webm", "mov", "avi", "wmv", "flv", "mpg", "mpeg",
                          "ts", "m2ts", "3gp", "ogv"}

# CRF por codec e nível. Valores menores = mais qualidade e arquivo maior.
# "alta" fica na faixa considerada visualmente sem perdas.
CRF = {
    "h264": {"alta": 18, "equilibrada": 22, "maxima": 26},
    "h265": {"alta": 20, "equilibrada": 24, "maxima": 28},
    "av1": {"alta": 24, "equilibrada": 30, "maxima": 36},
}

# Codecs que podem ser copiados (sem recodificar) para cada contêiner
COPY_VIDEO = {"mp4": {"h264", "hevc", "av1", "mpeg4"}, "mov": {"h264", "hevc", "mpeg4", "prores"}}
COPY_AUDIO = {"mp4": {"aac", "mp3", "ac3", "eac3", "alac", "opus", "flac"},
              "mov": {"aac", "mp3", "ac3", "alac", "pcm_s16le", "pcm_s24le"}}


class FFmpegError(RuntimeError):
    pass


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


@dataclass
class MediaInfo:
    duration: float
    video_codec: str | None
    audio_codec: str | None
    width: int | None
    height: int | None


def probe(path: Path) -> MediaInfo:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise FFmpegError("Não foi possível ler o vídeo: " + (result.stderr.strip() or "formato inválido"))
    data = json.loads(result.stdout or "{}")
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    if video is None:
        raise FFmpegError("O arquivo não contém uma faixa de vídeo.")
    try:
        duration = float(data.get("format", {}).get("duration") or video.get("duration") or 0)
    except ValueError:
        duration = 0.0
    return MediaInfo(
        duration=duration,
        video_codec=video.get("codec_name"),
        audio_codec=audio.get("codec_name") if audio else None,
        width=video.get("width"),
        height=video.get("height"),
    )


def _video_encoder_args(codec: str, level: str) -> list[str]:
    crf = str(CRF[codec][level])
    if codec == "h265":
        return ["-c:v", "libx265", "-preset", "slow", "-crf", crf, "-tag:v", "hvc1",
                "-x265-params", "log-level=error", "-pix_fmt", "yuv420p"]
    if codec == "av1":
        return ["-c:v", "libsvtav1", "-preset", "6", "-crf", crf, "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "slow", "-crf", crf, "-pix_fmt", "yuv420p"]


def _audio_args(info: MediaInfo, container: str = "mp4") -> list[str]:
    if info.audio_codec is None:
        return []
    if info.audio_codec in COPY_AUDIO[container]:
        return ["-c:a", "copy"]
    return ["-c:a", "aac", "-b:a", "192k"]


def build_compress_command(src: Path, dst: Path, info: MediaInfo, codec: str, level: str) -> list[str]:
    """Recomprime o vídeo mantendo resolução e taxa de quadros; o áudio é copiado quando possível."""
    return [
        "-i", str(src),
        "-map", "0:v:0", "-map", "0:a?",
        *_video_encoder_args(codec, level),
        *_audio_args(info),
        "-map_metadata", "0",
        "-movflags", "+faststart",
        str(dst),
    ]


def build_convert_command(src: Path, dst: Path, info: MediaInfo, target: str, level: str) -> list[str]:
    """Converte para outro contêiner, copiando as faixas sem recodificar sempre que o destino aceita."""
    if target == "gif":
        fps = 15
        width = min(info.width or 640, 640)
        graph = (f"fps={fps},scale={width}:-2:flags=lanczos,split[a][b];"
                 "[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=sierra2_4a")
        return ["-i", str(src), "-filter_complex", graph, "-loop", "0", str(dst)]

    if target == "webm":
        crf = {"alta": "28", "equilibrada": "33", "maxima": "38"}[level]
        audio = ["-c:a", "libopus", "-b:a", "128k"] if info.audio_codec else []
        if info.video_codec in {"vp8", "vp9", "av1"} and info.audio_codec in {None, "opus", "vorbis"}:
            return ["-i", str(src), "-map", "0:v:0", "-map", "0:a?", "-c", "copy", str(dst)]
        return ["-i", str(src), "-map", "0:v:0", "-map", "0:a?",
                "-c:v", "libvpx-vp9", "-crf", crf, "-b:v", "0", "-row-mt", "1",
                "-deadline", "good", "-cpu-used", "2", *audio, str(dst)]

    if target == "mkv":
        # Matroska aceita praticamente qualquer codec: cópia direta, sem perda.
        return ["-i", str(src), "-map", "0:v", "-map", "0:a?", "-c", "copy", str(dst)]

    if target in ("mp4", "mov"):
        faststart = ["-movflags", "+faststart"]
        if info.video_codec in COPY_VIDEO[target]:
            video = ["-c:v", "copy"]
            if info.video_codec == "hevc":
                video += ["-tag:v", "hvc1"]
        else:
            video = _video_encoder_args("h264", "alta")
        return ["-i", str(src), "-map", "0:v:0", "-map", "0:a?", *video,
                *_audio_args(info, target), *faststart, str(dst)]

    if target == "avi":
        audio = ["-c:a", "libmp3lame", "-q:a", "2"] if info.audio_codec else []
        return ["-i", str(src), "-map", "0:v:0", "-map", "0:a?",
                *_video_encoder_args("h264", "alta"), *audio, str(dst)]

    raise ValueError(f"Formato de vídeo não suportado: {target}")


_TIME_RE = re.compile(r"out_time_us=(\d+)")


def run_ffmpeg(args: list[str], duration: float, on_progress: Callable[[float], None] | None = None) -> None:
    """Executa o FFmpeg reportando o progresso (0 a 1) a partir de `-progress`."""
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
           "-progress", "pipe:1", "-nostats", *args]
    # stderr vai para um arquivo temporário para não travar o processo enquanto lemos o stdout.
    with tempfile.TemporaryFile(mode="w+") as err:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err, text=True)
        assert proc.stdout is not None
        for line in proc.stdout:
            match = _TIME_RE.match(line.strip())
            if match and duration > 0 and on_progress:
                on_progress(min(int(match.group(1)) / 1_000_000 / duration, 0.99))
        code = proc.wait()
        err.seek(0)
        stderr = err.read()
    if code != 0:
        raise FFmpegError("Falha no FFmpeg: " + (stderr.strip()[-800:] or "erro desconhecido"))
