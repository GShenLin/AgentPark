def test_provider_specific_http_errors_share_base_fields():
    from src.providers.doubao_agent_common import _CurlHTTPError
    from src.providers.openai_transport_errors import OpenAIHttpError
    from src.providers.provider_errors import ProviderHttpError
    from src.providers.zhipu_http_transport import ZhipuHttpError

    errors = [
        OpenAIHttpError(400, "openai-body"),
        _CurlHTTPError(401, "doubao-body"),
        ZhipuHttpError(402, "zhipu-body"),
    ]

    assert all(isinstance(error, ProviderHttpError) for error in errors)
    assert [error.status_code for error in errors] == [400, 401, 402]
    assert [error.response_body for error in errors] == ["openai-body", "doubao-body", "zhipu-body"]
    assert str(errors[0]) == "HTTP 400: openai-body"
    assert str(errors[1]) == "HTTP Error 401: doubao-body"
    assert str(errors[2]) == "HTTP 402: zhipu-body"


def test_provider_transport_and_input_errors_share_base_classes():
    from src.providers.curl_transport import CurlTransportError
    from src.providers.doubao_agent_common import _CurlTransportError
    from src.providers.openai_transport_errors import OpenAITransportError
    from src.providers.provider_errors import ProviderImageAttachmentError
    from src.providers.provider_errors import ProviderInputError
    from src.providers.provider_errors import ProviderTransportError
    from src.providers.zhipu_http_transport import ZhipuTransportError

    transport_errors = [
        CurlTransportError("curl"),
        OpenAITransportError("openai"),
        _CurlTransportError("doubao"),
        ZhipuTransportError("zhipu"),
    ]

    assert all(isinstance(error, ProviderTransportError) for error in transport_errors)
    assert isinstance(ProviderImageAttachmentError("bad image"), ProviderInputError)
