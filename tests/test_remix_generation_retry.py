import base64
import io
from unittest.mock import patch
from PIL import Image
import pytest
from server import creator_tools,image_provider


def image_result():
    stream=io.BytesIO();Image.new('RGB',(768,1024),'white').save(stream,format='PNG')
    return {'data':[{'b64_json':base64.b64encode(stream.getvalue()).decode()}]}


def test_confirmed_cancel_can_use_blank_canvas_once(tmp_path):
    error=image_provider.ImageProviderError('动态超时，本次请求已由平台取消，不计入费用')
    with patch.object(image_provider,'generate',side_effect=[error,image_result()]) as generate:
        creator_tools.generate_remix_card({}, {'headline':'测试'},1,1,tmp_path)
    assert generate.call_count==2
    assert generate.call_args_list[1].args[0]['reference_image'].startswith('data:image/png;base64,')


def test_required_person_reference_is_never_dropped(tmp_path):
    error=image_provider.ImageProviderError('动态超时，本次请求已由平台取消')
    with patch.object(image_provider,'generate',side_effect=error) as generate:
        with pytest.raises(image_provider.ImageProviderError):
            creator_tools.generate_remix_card({'preserve_person':True,'person_reference':'required'}, {},1,1,tmp_path)
    assert generate.call_count==1


def test_unknown_transport_failure_is_not_retried(tmp_path):
    with patch.object(image_provider,'generate',side_effect=image_provider.ImageProviderError('连接中断')) as generate:
        with pytest.raises(image_provider.ImageProviderError): creator_tools.generate_remix_card({}, {},1,1,tmp_path)
    assert generate.call_count==1
