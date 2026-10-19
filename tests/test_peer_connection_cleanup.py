"""Negotiation failures must release only the connection that failed."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.peer_network.connections import Link, PeerConnections
from src.peer_network.identity import DeviceIdentity


@pytest.mark.parametrize('phase', ['channel', 'offer', 'local', 'send', 'remote-offer', 'answer', 'remote-answer'])
@pytest.mark.parametrize('failure', [RuntimeError, TimeoutError, asyncio.CancelledError])
def test_failed_negotiation_closes_link(phase, failure):
    async def scenario():
        identities = sorted(
            [DeviceIdentity(Ed25519PrivateKey.generate()) for _ in range(2)],
            key=lambda identity: identity.peer_id,
        )
        incoming = phase in {'remote-offer', 'answer'}
        local, remote = identities[::-1] if incoming else identities
        service = SimpleNamespace(identity=local, store=SimpleNamespace(grants={remote.peer_id: object()}),
                                  send_signal=AsyncMock())
        connections = PeerConnections(service)
        pc = SimpleNamespace(
            connectionState='new', signalingState='have-local-offer',
            localDescription=SimpleNamespace(sdp='test-sdp'),
            createDataChannel=Mock(), createOffer=AsyncMock(), createAnswer=AsyncMock(),
            setLocalDescription=AsyncMock(), setRemoteDescription=AsyncMock(), close=AsyncMock(),
        )
        channel = SimpleNamespace(close=Mock())
        link = Link('a' * 32, pc, 0, channel=channel)

        async def new(peer, session_id):
            link.session_id = session_id
            connections.links[peer] = link
            return link

        connections.new = new
        connections.bind = Mock()
        operation = {
            'channel': pc.createDataChannel, 'offer': pc.createOffer,
            'local': pc.setLocalDescription, 'send': service.send_signal,
            'remote-offer': pc.setRemoteDescription, 'answer': pc.createAnswer,
            'remote-answer': pc.setRemoteDescription,
        }[phase]
        operation.side_effect = failure('negotiation failed')
        if phase == 'remote-answer':
            connections.links[remote.peer_id] = link
        with pytest.raises(failure, match='negotiation failed'):
            if incoming or phase == 'remote-answer':
                kind = 'offer' if incoming else 'answer'
                await connections.accept(remote.signal(kind, local.peer_id, link.session_id, 'test-sdp'))
            else:
                await connections.connect(remote.peer_id)
        assert remote.peer_id not in connections.links
        pc.close.assert_awaited_once()
        channel.close.assert_called_once()
        assert connections.changed.is_set()

    asyncio.run(scenario())


def test_late_failure_does_not_remove_replacement_link():
    async def scenario():
        service = SimpleNamespace(identity=SimpleNamespace(peer_id='a'),
                                  store=SimpleNamespace(grants={'b': object()}), send_signal=AsyncMock())
        connections = PeerConnections(service)
        old = Link('old', SimpleNamespace(createDataChannel=Mock(), setLocalDescription=AsyncMock(), close=AsyncMock()), 0)
        replacement = Link('replacement', SimpleNamespace(close=AsyncMock()), 1)

        async def new(*_):
            connections.links['b'] = old
            return old

        async def fail_after_replacement():
            connections.links['b'] = replacement
            raise RuntimeError('late failure')

        old.pc.createOffer = fail_after_replacement
        connections.new = new
        connections.bind = Mock()
        with pytest.raises(RuntimeError, match='late failure'):
            await connections.connect('b')
        assert connections.links['b'] is replacement
        old.pc.close.assert_awaited_once()
        replacement.pc.close.assert_not_called()

    asyncio.run(scenario())
