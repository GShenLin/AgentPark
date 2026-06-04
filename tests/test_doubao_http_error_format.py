from src.providers.doubao_agent_common import format_doubao_http_error


def test_format_doubao_http_error_translates_real_person_image_rejection():
    body = (
        '{"error":{"code":"InputImageSensitiveContentDetected.PrivacyInformation",'
        '"message":"The request failed because the input image may contain real person. '
        'Request id: 021776240483057265634cfb9c55dca3322eb639399abf189664f",'
        '"param":"","type":"BadRequest"}}'
    )

    message = format_doubao_http_error(400, body)

    assert "检测到图片可能包含真人或隐私信息" in message
    assert "不支持把真人照片作为参考图、首帧或尾帧" in message
    assert "InputImageSensitiveContentDetected.PrivacyInformation" in message
    assert "021776240483057265634cfb9c55dca3322eb639399abf189664f" in message


def test_format_doubao_http_error_preserves_generic_structured_error():
    body = '{"error":{"code":"SomeOtherError","message":"something failed","type":"BadRequest"}}'

    message = format_doubao_http_error(400, body)

    assert message == "HTTP Error 400: SomeOtherError: something failed"
