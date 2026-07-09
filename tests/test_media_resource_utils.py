from src.media_resource_utils import resolve_public_base_url


def test_resolve_public_base_url_precedence(monkeypatch):
    class Loader:
        def get_config(self):
            return {"publicBaseUrl": "https://workspace.example.com"}

        def get_provider_config(self, provider_id):
            return {"publicBaseUrl": f"https://{provider_id}.example.com"}

    import src.media_resource_utils as media_utils

    monkeypatch.setattr(media_utils, "ConfigLoader", Loader)
    monkeypatch.setenv("AGENTPARK_PUBLIC_BASE_URL", "https://env.example.com/")

    assert resolve_public_base_url("https://explicit.example.com/", "demo") == "https://explicit.example.com"
    assert resolve_public_base_url("", "demo") == "https://env.example.com"

    monkeypatch.delenv("AGENTPARK_PUBLIC_BASE_URL")

    assert resolve_public_base_url("", "demo") == "https://workspace.example.com"


def test_resolve_public_base_url_falls_back_to_provider(monkeypatch):
    class Loader:
        def get_config(self):
            return {}

        def get_provider_config(self, provider_id):
            return {"publicBaseUrl": f"https://{provider_id}.example.com/"}

    import src.media_resource_utils as media_utils

    monkeypatch.setattr(media_utils, "ConfigLoader", Loader)
    monkeypatch.delenv("AGENTPARK_PUBLIC_BASE_URL", raising=False)

    assert resolve_public_base_url("", "demo") == "https://demo.example.com"
