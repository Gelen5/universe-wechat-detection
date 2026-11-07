from io import BytesIO
from pathlib import Path
import pytest
from PIL import Image
from server.content_factory_image import inspect_image, render


@pytest.fixture
def font():
    candidates = [Path('C:/Windows/Fonts/msyh.ttc'), Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')]
    result = next((path for path in candidates if path.is_file()), None)
    if not result:
        pytest.skip('Chinese font is unavailable')
    return result


def image_bytes(size):
    stream = BytesIO()
    Image.new('RGB', size, 'navy').save(stream, format='PNG')
    return stream.getvalue()


def test_render_chinese_title_preserves_format_and_safe_layout(font):
    result = render(image_bytes((300, 400)), '和家人好好说话', font_path=font)
    with Image.open(BytesIO(result['image'])) as image:
        assert image.size == (1080, 1440) and image.format == 'PNG'
    assert result['line_count'] >= 1 and result['text'] == '和家人好好说话'
    assert result['limitations']
    assert inspect_image(result['image']) == {'image_decode': True, 'image_dimensions': True, 'opaque': True}


def test_invalid_or_incorrect_ratio_never_silently_passes(font):
    with pytest.raises(ValueError): render(b'not an image', '标题', font_path=font)
    with pytest.raises(ValueError): render(image_bytes((400, 400)), '标题', font_path=font)
    with pytest.raises(ValueError): render(image_bytes((300, 400)), '文' * 81, font_path=font)
    assert not inspect_image(b'broken')['image_decode']
