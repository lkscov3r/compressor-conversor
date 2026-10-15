import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import video
from app.main import app

client = TestClient(app)
needs_ffmpeg = pytest.mark.skipif(not video.ffmpeg_available(), reason="FFmpeg não instalado")


def wait_for(job_id: str, timeout: float = 120) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("concluido", "erro"):
            return job
        time.sleep(0.2)
    raise TimeoutError(job_id)


def submit(path: Path, **form) -> dict:
    with path.open("rb") as fh:
        res = client.post("/api/jobs", files={"file": (path.name, fh)}, data=form)
    assert res.status_code == 200, res.text
    return wait_for(res.json()["id"])


@pytest.fixture
def png_with_alpha(tmp_path: Path) -> Path:
    path = tmp_path / "foto.png"
    img = Image.radial_gradient("L").resize((400, 300)).convert("RGBA")
    img.putalpha(200)
    img.save(path)
    return path


@pytest.fixture(scope="session")
def sample_video(tmp_path_factory) -> Path:
    if not video.ffmpeg_available():
        pytest.skip("FFmpeg não instalado")
    path = tmp_path_factory.mktemp("v") / "clipe.mov"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=3",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
         "-c:v", "mjpeg", "-q:v", "2", "-c:a", "pcm_s16le", "-shortest", str(path)],
        check=True,
    )
    return path


def download(job: dict) -> bytes:
    res = client.get(f"/api/jobs/{job['id']}/download")
    assert res.status_code == 200
    return res.content


def test_info():
    data = client.get("/api/info").json()
    assert "mp4" in data["video"]["output"]
    assert "webp" in data["image"]["output"]


def test_index_served():
    res = client.get("/")
    assert res.status_code == 200
    assert "Compressor" in res.text


def test_rejects_unknown_format(tmp_path: Path):
    path = tmp_path / "x.txt"
    path.write_text("oi")
    with path.open("rb") as fh:
        res = client.post("/api/jobs", files={"file": ("x.txt", fh)})
    assert res.status_code == 400


@pytest.mark.parametrize("target", ["jpg", "webp", "avif", "gif", "bmp", "tiff", "png"])
def test_convert_image(png_with_alpha: Path, tmp_path: Path, target: str):
    job = submit(png_with_alpha, operation="convert", target_format=target)
    assert job["status"] == "concluido", job.get("error")
    out = tmp_path / f"out.{target}"
    out.write_bytes(download(job))
    with Image.open(out) as img:
        assert img.size == (400, 300)


def test_convert_image_lossless_webp(png_with_alpha: Path, tmp_path: Path):
    job = submit(png_with_alpha, operation="convert", target_format="webp", lossless="true")
    out = tmp_path / "out.webp"
    out.write_bytes(download(job))
    with Image.open(out) as a, Image.open(png_with_alpha) as b:
        assert a.convert("RGBA").tobytes() == b.convert("RGBA").tobytes()


def test_compress_jpeg(tmp_path: Path):
    path = tmp_path / "foto.jpg"
    Image.effect_noise((800, 600), 40).convert("RGB").save(path, quality=100)
    job = submit(path, operation="compress", level="alta")
    assert job["status"] == "concluido"
    assert job["download_name"] == "foto_comprimido.jpg"
    assert job["output_size"] < job["input_size"]


@needs_ffmpeg
@pytest.mark.parametrize("codec", ["h264", "h265"])
def test_compress_video(sample_video: Path, tmp_path: Path, codec: str):
    job = submit(sample_video, operation="compress", level="alta", codec=codec)
    assert job["status"] == "concluido", job.get("error")
    assert job["output_size"] < job["input_size"]
    out = tmp_path / "out.mp4"
    out.write_bytes(download(job))
    info = video.probe(out)
    assert info.video_codec == {"h264": "h264", "h265": "hevc"}[codec]
    assert (info.width, info.height) == (640, 360)
    assert info.audio_codec == "aac"
    assert info.duration == pytest.approx(3, abs=0.2)


@needs_ffmpeg
@pytest.mark.parametrize("target", ["mp4", "mkv", "webm", "mov", "avi", "gif"])
def test_convert_video(sample_video: Path, tmp_path: Path, target: str):
    job = submit(sample_video, operation="convert", target_format=target, level="maxima")
    assert job["status"] == "concluido", job.get("error")
    out = tmp_path / f"out.{target}"
    out.write_bytes(download(job))
    assert video.probe(out).width == 640


@needs_ffmpeg
def test_mkv_is_stream_copy(sample_video: Path, tmp_path: Path):
    job = submit(sample_video, operation="convert", target_format="mkv")
    out = tmp_path / "out.mkv"
    out.write_bytes(download(job))
    info = video.probe(out)
    assert info.video_codec == "mjpeg" and info.audio_codec == "pcm_s16le"
