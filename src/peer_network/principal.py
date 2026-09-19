from dataclasses import dataclass


@dataclass(frozen=True)
class PeerPrincipal:
    """Created only after cryptographic transport authentication, never from HTTP headers."""

    peer_id: str
    name: str


@dataclass(frozen=True)
class CloudBoardAdministrator(PeerPrincipal):
    """Issued by the Board dispatcher only after validating a coordinator ticket."""
