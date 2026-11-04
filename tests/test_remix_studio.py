import base64
import io
import pytest
from PIL import Image
from server import remix_studio as studio


def test_guidance_is_optional_and_revision_is_scoped():
    assert studio.option_text([])==[]
    assert len(studio.option_text(['stronger','stronger']))==1
    prompt=studio.design_instructions('标题更醒目',['headline'],{'headline':'旧标题'})
    assert '仅改用户点名的部分' in prompt
    assert '旧标题' in prompt
    assert '只交付一张图' in prompt


def test_invalid_or_conflicting_options_are_rejected():
    for keys in (['unknown'],['no_text','facts']):
        with pytest.raises(ValueError): studio.option_text(keys)


def test_source_is_validated_before_reservation():
    buffer=io.BytesIO();Image.new('RGB',(80,100),'green').save(buffer,format='PNG')
    source='data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode()
    assert studio.validate_reference(source)==source
    with pytest.raises(ValueError): studio.validate_reference('https://untrusted/image.png')
