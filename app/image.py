"""Compressão e conversão de imagens com Pillow."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

# Extensão de saída -> formato do Pillow
IMAGE_FORMATS: dict[str, str] = {
    "jpg": "JPEG",
    "png": "PNG",
    "webp": "WEBP",
    "avif": "AVIF",
    "gif": "GIF",
    "bmp": "BMP",
    "tiff": "TIFF",
}

IMAGE_INPUT_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "avif", "gif", "bmp", "tif", "tiff"}

# Qualidade por nível de compressão (formatos com perda: JPEG, WebP, AVIF)
QUALITY = {
    "alta": {"JPEG": 90, "WEBP": 90, "AVIF": 80},
    "equilibrada": {"JPEG": 82, "WEBP": 82, "AVIF": 65},
    "maxima": {"JPEG": 70, "WEBP": 70, "AVIF": 50},
}

NO_ALPHA_FORMATS = {"JPEG", "BMP"}


def normalize_extension(ext: str) -> str:
    ext = ext.lower().lstrip(".")
    return {"jpeg": "jpg", "tif": "tiff"}.get(ext, ext)


def _flatten_alpha(img: Image.Image) -> Image.Image:
    """Remove transparência colocando a imagem sobre fundo branco."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return img.convert("RGB")


def _save_options(fmt: str, level: str, img: Image.Image, source: Image.Image) -> dict:
    opts: dict = {}
    exif = source.getexif()
    if exif and fmt in ("JPEG", "WEBP", "AVIF", "PNG", "TIFF"):
        # A orientação já foi aplicada aos pixels; zera a tag para não girar duas vezes.
        exif[0x0112] = 1
        opts["exif"] = exif.tobytes()
    icc = source.info.get("icc_profile")
    if icc and fmt in ("JPEG", "WEBP", "AVIF", "PNG", "TIFF"):
        opts["icc_profile"] = icc

    if fmt == "JPEG":
        opts.update(quality=QUALITY[level]["JPEG"], optimize=True, progressive=True)
        # Na qualidade "alta" mantém a cor em resolução cheia (sem subamostragem 4:2:0).
        opts["subsampling"] = 0 if level == "alta" else 2
    elif fmt == "WEBP":
        opts.update(quality=QUALITY[level]["WEBP"], method=6)
    elif fmt == "AVIF":
        opts.update(quality=QUALITY[level]["AVIF"], speed=6)
    elif fmt == "PNG":
        opts.update(optimize=True)
    elif fmt == "TIFF":
        opts.update(compression="tiff_lzw")
    elif fmt == "GIF":
        opts.update(optimize=True)
    return opts


def process_image(src: Path, dst: Path, target_ext: str, level: str = "alta",
                  lossless: bool = False) -> None:
    """Converte/comprime `src` para `dst` no formato `target_ext`.

    `lossless=True` usa modo sem perdas quando o formato de destino permite
    (PNG, WebP lossless, TIFF LZW); para JPEG apenas otimiza a codificação.
    """
    target_ext = normalize_extension(target_ext)
    fmt = IMAGE_FORMATS[target_ext]

    with Image.open(src) as source:
        source.load()
        img = ImageOps.exif_transpose(source)

        if fmt in NO_ALPHA_FORMATS:
            img = _flatten_alpha(img)
        elif fmt == "GIF":
            img = img.convert("RGBA") if img.mode in ("RGBA", "LA", "P") else img.convert("RGB")
        elif img.mode not in ("RGB", "RGBA", "L", "LA"):
            img = img.convert("RGBA" if "A" in img.getbands() or "transparency" in img.info else "RGB")

        opts = _save_options(fmt, level, img, source)

        if lossless and fmt == "WEBP":
            opts.pop("quality", None)
            opts.update(lossless=True, quality=100, method=6)
        elif lossless and fmt == "AVIF":
            opts.update(quality=100)
        elif fmt == "PNG" and level == "maxima" and not lossless:
            # Reduz para paleta de 256 cores: arquivo bem menor, perda geralmente imperceptível.
            if img.mode in ("RGBA", "LA"):
                img = img.convert("RGBA").quantize(colors=256, method=Image.Quantize.FASTOCTREE)
            else:
                img = img.convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT)

        img.save(dst, format=fmt, **opts)
