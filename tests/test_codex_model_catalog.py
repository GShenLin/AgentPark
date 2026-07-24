import pytest

from src.codex_runtime.model_catalog import CodexModelCatalogError
from src.codex_runtime.model_catalog import resolve_codex_runtime_model


def _request_for(pages):
    calls = []

    def request(method, params, **kwargs):
        calls.append((method, params, kwargs))
        cursor = str(params.get("cursor") or "")
        return pages[cursor]

    return request, calls


def _model(model, *, default=False, efforts=("high",)):
    return {
        "id": model,
        "model": model,
        "isDefault": default,
        "supportedReasoningEfforts": [
            {"reasoningEffort": effort, "description": effort}
            for effort in efforts
        ],
    }


def test_runtime_model_uses_exact_catalog_model_when_available():
    request, calls = _request_for({
        "": {"data": [_model("gpt-requested"), _model("gpt-default", default=True)], "nextCursor": None},
    })

    selection = resolve_codex_runtime_model(request, "gpt-requested", reasoning_effort="high")

    assert selection.runtime_model == "gpt-requested"
    assert selection.source == "requested"
    assert calls[0][0] == "model/list"
    assert calls[0][1]["includeHidden"] is True


def test_runtime_model_uses_unique_catalog_default_for_custom_provider_model():
    request, _calls = _request_for({
        "": {"data": [_model("gpt-old")], "nextCursor": "page-2"},
        "page-2": {"data": [_model("gpt-runtime", default=True)], "nextCursor": None},
    })

    selection = resolve_codex_runtime_model(request, "provider-private-model", reasoning_effort="high")

    assert selection.requested_model == "provider-private-model"
    assert selection.runtime_model == "gpt-runtime"
    assert selection.source == "catalog_default"


@pytest.mark.parametrize(
    "models, message",
    [
        ([_model("a"), _model("b")], "found 0"),
        ([_model("a", default=True), _model("b", default=True)], "found 2"),
    ],
)
def test_runtime_model_rejects_ambiguous_or_missing_catalog_default(models, message):
    request, _calls = _request_for({"": {"data": models, "nextCursor": None}})

    with pytest.raises(CodexModelCatalogError, match=message):
        resolve_codex_runtime_model(request, "provider-private-model")


def test_runtime_model_rejects_unsupported_reasoning_effort():
    request, _calls = _request_for({
        "": {"data": [_model("gpt-runtime", default=True, efforts=("low", "medium"))], "nextCursor": None},
    })

    with pytest.raises(CodexModelCatalogError, match="does not support reasoning effort 'high'"):
        resolve_codex_runtime_model(request, "provider-private-model", reasoning_effort="high")
