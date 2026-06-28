from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CapabilityRef:
    kind: str
    id: str

    def to_payload(self) -> dict[str, str]:
        return {"kind": self.kind, "id": self.id}


@dataclass(frozen=True)
class CapabilityDescriptor:
    kind: str
    id: str
    label: str
    description: str = ""
    version: str = ""
    source: str = "workspace"
    enabled: bool = False
    dependencies: tuple[CapabilityRef, ...] = ()
    config_schema: dict[str, Any] = field(default_factory=dict)
    status: str = "available"
    diagnostics: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "version": self.version,
            "source": self.source,
            "enabled": self.enabled,
            "dependencies": [item.to_payload() for item in self.dependencies],
            "config_schema": self.config_schema,
            "status": self.status,
            "diagnostics": list(self.diagnostics),
        }
