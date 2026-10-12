"""Official release discovery must not depend on GitHub's anonymous REST API."""
import pytest

from src.harness import hermes_release
from src.harness.hermes_release import HermesRelease
from src.providers.curl_transport import CurlHttpError, CurlTransportError
from src.providers.curl_types import CurlResponse


def mock_requests(monkeypatch, responses):
    calls = []
    pending = iter(responses)

    def request(self, **kwargs):
        calls.append(kwargs)
        response = next(pending)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(hermes_release.CurlHttpTransport, "request", request)
    return calls


def redirect(location):
    return CurlResponse("", 302, {"location": location})


@pytest.mark.parametrize(("tag", "version"), [
    ("v2026.9.14", "0.21.3"), ("v0.21.6", "0.21.6"),
])
def test_release_uses_official_redirect_and_tagged_package_version(monkeypatch, tag, version):
    calls = mock_requests(monkeypatch, [
        redirect(f"{hermes_release.RELEASES_URL}/tag/{tag}"),
        CurlResponse(f'[project]\nname="hermes-agent"\nversion="{version}"', 200),
    ])
    assert hermes_release.latest_release() == HermesRelease(tag, version)
    assert len(calls) == 2
    assert calls[0]["url"] == f"{hermes_release.RELEASES_URL}/latest"
    assert calls[0]["method"] == "HEAD"
    assert calls[0]["follow_redirects"] is False
    assert calls[1]["url"] == f"https://raw.githubusercontent.com/NousResearch/hermes-agent/{tag}/pyproject.toml"
    for call in calls:
        assert call["timeout_sec"] == 20
        assert call["max_response_bytes"] <= 2 * 1024 * 1024 + 1
        assert "authorization" not in {name.lower() for name in call["headers"]}


@pytest.mark.parametrize("location", [
    "", "https://example.com/NousResearch/hermes-agent/releases/tag/v0.21.6",
    "https://github.com/other/hermes-agent/releases/tag/v0.21.6",
    "https://github.com/NousResearch/hermes-agent/releases",
    "https://github.com/NousResearch/hermes-agent/releases/tag/../../bad",
    "https://github.com/NousResearch/hermes-agent/releases/tag/v0.21.6-rc.1",
    "https://github.com/NousResearch/hermes-agent/releases/tag/v0.21.6?other=1",
    "http://github.com/NousResearch/hermes-agent/releases/tag/v0.21.6",
])
def test_invalid_release_redirect_stops_before_manifest_request(monkeypatch, location):
    calls = mock_requests(monkeypatch, [redirect(location)])
    with pytest.raises(ValueError, match="Invalid Hermes release redirect"):
        hermes_release.latest_release()
    assert len(calls) == 1


@pytest.mark.parametrize("status", [200, 301, 304, 307])
def test_unexpected_response_is_not_treated_as_a_release(monkeypatch, status):
    mock_requests(monkeypatch, [CurlResponse("", status)])
    with pytest.raises(ValueError, match="Expected a Hermes latest-release redirect"):
        hermes_release.latest_release()


@pytest.mark.parametrize("failure", [
    CurlResponse("Forbidden", 403), CurlResponse("Not Found", 404),
    CurlTransportError("GitHub unavailable"),
])
def test_network_failure_is_reported_without_api_fallback(monkeypatch, failure):
    calls = mock_requests(monkeypatch, [failure])
    with pytest.raises((CurlHttpError, CurlTransportError)):
        hermes_release.latest_release()
    assert len(calls) == 1


@pytest.mark.parametrize("manifest", [
    '[project]\nname="other-package"\nversion="0.21.6"',
    '[project]\nname="hermes-agent"\nversion="invalid"',
    '[project]\nname="hermes-agent"', 'invalid toml',
])
def test_invalid_manifest_never_produces_a_release(monkeypatch, manifest):
    mock_requests(monkeypatch, [
        redirect(f"{hermes_release.RELEASES_URL}/tag/v0.21.6"),
        CurlResponse(manifest, 200),
    ])
    with pytest.raises(ValueError):
        hermes_release.latest_release()


def test_pm_release_uses_semver_tag_as_runtime_identity(monkeypatch):
    mock_requests(monkeypatch, [
        redirect(f"{hermes_release.RELEASES_URL}/tag/v0.21.6"),
        CurlResponse('[project]\nname="hermes-agent"\nversion="0.0.0"', 200),
    ])
    assert hermes_release.latest_release() == HermesRelease("v0.21.6", "0.21.6", "pm")


def test_pm_placeholder_cannot_use_calendar_tag_as_runtime_version(monkeypatch):
    mock_requests(monkeypatch, [
        redirect(f"{hermes_release.RELEASES_URL}/tag/v2026.9.24"),
        CurlResponse('[project]\nname="hermes-agent"\nversion="0.0.0"', 200),
    ])
    with pytest.raises(ValueError, match="semantic version release tag"):
        hermes_release.latest_release()
