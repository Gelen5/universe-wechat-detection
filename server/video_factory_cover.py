"""Create a deterministic cover from the first generated scene."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
)


def _font(size: int):
    for candidate in FONT_CANDIDATES:
        if Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def create_cover(scene_image: Path, output: Path, title: str) -> None:
    if output.exists():
        raise FileExistsError("cover already exists")
    if not scene_image.is_file() or not scene_image.stat().st_size:
        raise ValueError("scene image is missing")
    text = str(title or "").strip()
    if not text:
        raise ValueError("cover title is empty")
    with Image.open(scene_image) as source:
        image = ImageOps.fit(source.convert("RGB"), (1080, 1920), method=Image.Resampling.LANCZOS)
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = _font(104)
    margin = 84
    max_width = image.width - margin * 2
    lines = []
    current = ""
    for char in text:
        candidate = current + char
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = char
    if current:
        lines.append(current)
    lines = lines[:3]
    line_height = 132
    block_height = len(lines) * line_height
    top = image.height - 260 - block_height
    draw.rounded_rectangle((42, max(80, top - 44), image.width - 42, top + block_height + 36),
                           radius=32, fill=(14, 30, 24, 176))
    for index, line in enumerate(lines):
        draw.text((margin, top + index * line_height), line, font=font,
                  fill=(255, 250, 239, 255), stroke_width=4, stroke_fill=(12, 24, 20, 255))
    Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB").save(output, format="JPEG", quality=92)
