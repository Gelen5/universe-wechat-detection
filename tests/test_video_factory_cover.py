from pathlib import Path

from PIL import Image, ImageDraw

from server.video_factory_cover import create_cover


def test_cover_is_vertical_and_rendered_from_scene(tmp_path):
    scene = tmp_path / 'scene.png'
    output = tmp_path / 'cover.jpg'
    image = Image.new('RGB', (1080, 1920), '#708c7a')
    ImageDraw.Draw(image).rectangle((0, 1000, 1080, 1920), fill='#19382e')
    image.save(scene)
    create_cover(scene, output, '曾国藩家书')
    assert output.is_file()
    with Image.open(output) as cover:
        assert cover.size == (1080, 1920)
        assert cover.format == 'JPEG'


def test_cover_refuses_to_replace_existing_output(tmp_path):
    scene = tmp_path / 'scene.png'
    output = tmp_path / 'cover.jpg'
    Image.new('RGB', (108, 192)).save(scene)
    output.write_bytes(b'existing')
    try:
        create_cover(scene, output, '标题')
    except FileExistsError:
        pass
    else:
        raise AssertionError('cover replacement must be explicit')
