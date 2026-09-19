import asyncio

import pytest
from pydantic import ValidationError

from src.peer_network.contracts import DeviceSetup
from src.peer_network.service import PeerNetworkService
from src.peer_network.store import PeerStore


def test_device_name_defaults_to_hostname(monkeypatch):
    monkeypatch.setattr('src.peer_network.contracts.socket.gethostname', lambda: 'MY-PC')
    assert DeviceSetup().display_name == 'MY-PC'
    assert DeviceSetup(server_ip='203.0.113.10').connection_settings().display_name == 'MY-PC'


def test_new_device_defaults_and_saved_settings_are_distinct(tmp_path):
    store = PeerStore(tmp_path)
    assert store.settings.enabled is True
    assert store.settings.server_ip == '203.0.113.10'
    assert store.settings.signaling_url == 'wss://203.0.113.10/connect'
    assert store.settings.stun_urls == ['stun:203.0.113.10:3478']
    store.settings = DeviceSetup(enabled=False, server_ip='192.0.2.10').connection_settings()
    store.save()
    restored = PeerStore(tmp_path)
    assert restored.settings.enabled is False
    assert restored.settings.server_ip == '192.0.2.10'


@pytest.mark.parametrize('value', ['', '   ', 'x' * 101])
def test_invalid_device_name_is_rejected(value):
    with pytest.raises(ValidationError):
        DeviceSetup(display_name=value)


def test_renaming_persists_without_changing_device_identity(tmp_path):
    service = PeerNetworkService(tmp_path, None)
    identity = service.identity.peer_id
    settings = DeviceSetup(enabled=False, server_ip='203.0.113.10', display_name='  我的工作电脑  ')
    asyncio.run(service.configure(settings.connection_settings()))
    assert service.status()['device_name'] == '我的工作电脑'
    assert service.status()['settings']['display_name'] == '我的工作电脑'
    reloaded = PeerNetworkService(tmp_path, None)
    assert reloaded.identity.peer_id == identity
    assert PeerStore(tmp_path).public_settings()['display_name'] == '我的工作电脑'
