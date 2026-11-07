"""Deterministic Chinese text layout for a supplied original background.

This module does not fetch images, call providers, or publish products.
"""
from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps

SIZE = (1080, 1440)
PANEL = (64, 80, 1016, 660)
TEXT_COLOR = (35, 35, 35)
PANEL_COLOR = (255, 255, 255)


def inspect_image(data):
    """Technical checks only; result says nothing about visuals or rights."""
    result = {'image_decode': False, 'image_dimensions': False, 'opaque': False}
    if not isinstance(data, bytes) or not 0 < len(data) <= 15 * 1024 * 1024:
        return result
    try:
        with Image.open(BytesIO(data)) as image:
            if image.width * image.height > 24_000_000:
                return result
            image.load()
            result['image_decode'] = True
            result['image_dimensions'] = (image.width >= 900 and image.width * 4 == image.height * 3)
            result['opaque'] = 'A' not in image.getbands() or image.getchannel('A').getextrema() == (255, 255)
    except (OSError, ValueError, Image.DecompressionBombError):
        return result
    return result


def _lines(draw, text, font, max_width):
    output = []
    for paragraph in text.splitlines():
        line = ''
        for char in paragraph:
            proposed = line + char
            if line and draw.textlength(proposed, font=font) > max_width:
                output.append(line)
                line = char
            else:
                line = proposed
        if line:
            output.append(line)
    return output


def _glyph_signature(font, char):
    mask = font.getmask(char, mode='L')
    return mask.size, hashlib.sha256(bytes(mask)).digest()


def _glyph_coverage(font, text):
    """Reject characters the selected font would render as .notdef boxes."""
    try:
        missing = _glyph_signature(font, '\U0010ffff')
        for char in text:
            if char.isspace():
                continue
            mask = font.getmask(char, mode='L')
            if mask.getbbox() is None or _glyph_signature(font, char) == missing:
                return False
    except (OSError, ValueError, TypeError):
        return False
    return True


def render(background, text, *, font_path, max_chars=80):
    if not isinstance(background, bytes) or not background or len(background) > 15 * 1024 * 1024:
        raise ValueError('invalid background')
    if not isinstance(text, str) or not text.strip() or len(text) > max_chars:
        raise ValueError('invalid text')
    text = text.strip()
    if any(ord(char) < 32 and char != '\n' for char in text):
        raise ValueError('invalid control character')
    if not Path(font_path).is_file():
        raise ValueError('font unavailable')
    try:
        with Image.open(BytesIO(background)) as source:
            if source.width * source.height > 24_000_000:
                raise ValueError('image too large')
            source.load()
            image = ImageOps.exif_transpose(source).convert('RGB')
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError('image cannot be decoded') from exc
    if image.width * 4 != image.height * 3:
        raise ValueError('background must be 3:4; no silent crop')
    image = image.resize(SIZE, Image.Resampling.LANCZOS)
    # An opaque light panel establishes a deterministic contrast, independent
    # of background luminance. All text stays inside fixed safe margins.
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(PANEL, radius=32, fill=PANEL_COLOR)
    max_width = 800
    glyph_coverage = False
    for size in range(76, 35, -2):
        font = ImageFont.truetype(str(font_path), size=size)
        glyph_coverage = _glyph_coverage(font, text)
        if not glyph_coverage:
            break
        lines = _lines(draw, text, font, max_width)
        spacing = int(size * 1.55)
        if lines and len(lines) <= 5 and len(lines) * spacing <= 440:
            break
    else:
        raise ValueError('text does not fit')
    if not glyph_coverage:
        raise ValueError('font does not cover every character')
    y = 150 + (440 - len(lines) * spacing) // 2
    text_bounds = None
    for line in lines:
        box = draw.textbbox((0, 0), line, font=font)
        if box[2] - box[0] > max_width:
            raise ValueError('text does not fit')
        x = (SIZE[0] - (box[2] - box[0])) // 2 - box[0]
        draw.text((x, y), line, font=font, fill=TEXT_COLOR)
        line_box = (x + box[0], y + box[1], x + box[2], y + box[3])
        text_bounds = line_box if text_bounds is None else (
            min(text_bounds[0], line_box[0]), min(text_bounds[1], line_box[1]),
            max(text_bounds[2], line_box[2]), max(text_bounds[3], line_box[3]))
        y += spacing
    inside_panel = bool(text_bounds and text_bounds[0] >= PANEL[0] and text_bounds[1] >= PANEL[1]
                        and text_bounds[2] <= PANEL[2] and text_bounds[3] <= PANEL[3])
    if not inside_panel:
        raise ValueError('text exceeds the safe area')
    output = BytesIO()
    image.save(output, format='PNG', optimize=True)
    return {'image': output.getvalue(), 'width': SIZE[0], 'height': SIZE[1],
            'text': text, 'line_count': len(lines), 'font_size': size,
            'checks': {'text_exact': True, 'text_fits': True, 'glyph_coverage': True,
                       'safe_area': True, 'contrast': True},
            # Deterministic layout, glyph and contrast checks are complete;
            # semantic visual quality, safety and rights still require vision.
            'limitations': ['需通过视觉复核确认语义、主体、变形、水印、安全及素材权利']}
