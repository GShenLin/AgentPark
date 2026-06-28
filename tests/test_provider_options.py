from src.provider_options import build_provider_options_for_support_modes, build_provider_support_list


def test_build_provider_options_for_support_modes_filters_and_sorts():
    providers = {
        "beta": {"supportmode": ["chat", "model_generation"]},
        "alpha": {"supportmode": ["image_generation"]},
        "ignored": {"supportmode": ["chat"]},
        "empty": {"supportmode": []},
    }

    options = build_provider_options_for_support_modes({"image_generation", "model_generation"}, providers)

    assert [item["value"] for item in options] == ["alpha", "beta"]


def test_build_provider_options_for_support_modes_handles_loader_failure(monkeypatch):
    import src.provider_options as provider_options_module

    class DummyLoader:
        def get_all_providers(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(provider_options_module, "ConfigLoader", lambda: DummyLoader())

    assert build_provider_options_for_support_modes({"image_generation"}) == []


def test_build_provider_support_list_defaults_missing_modes_to_chat():
    providers = build_provider_support_list(
        {
            "demo": {
                "features": {"thinking": {"supported": True}},
            }
        }
    )

    assert providers == [
        {
            "id": "demo",
            "supportmode": ["chat"],
            "features": {"thinking": {"supported": True}},
        }
    ]
