"""Execution-device overlay service. Capture IDs are mapped by exact physical bounds."""
import threading
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from src.desktop_capture.contracts import Contract, Display
from src.desktop_capture.windows import displays
from src.workspace_settings import get_workspace_root
from .contracts import AnnotationDrawing
from .host import AnnotationHost


class ExecutionAnnotationCommand(Contract):
    action: Literal['prepare', 'ping', 'clear', 'stop', 'draw']
    annotation_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')
    display_id: str | None = None
    drawing: AnnotationDrawing | None = None

    @model_validator(mode='after')
    def fields(self):
        if (self.action == 'prepare') != (self.annotation_id is None):
            raise ValueError('Active commands require an annotation identity.')
        if (self.action == 'draw') != (self.display_id is not None):
            raise ValueError('Draw requires the capture display identity.')
        if (self.action == 'draw') != (self.drawing is not None):
            raise ValueError('Only draw accepts a drawing.')
        return self


class ExecutionAnnotationResult(Contract):
    ok: Literal[True] = True
    annotation_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    displays: list[Display] = Field(default_factory=list)


class ExecutionAnnotations:
    def __init__(self):
        self._lock = threading.RLock()
        self._hosts: dict[str, tuple[AnnotationHost, dict[str, tuple[Display, str]]]] = {}

    def execute(self, command: ExecutionAnnotationCommand) -> ExecutionAnnotationResult:
        with self._lock:
            for identity, (host, _) in list(self._hosts.items()):
                if host.process.poll() is not None:
                    host.close()
                    del self._hosts[identity]
            if command.action == 'prepare':
                catalog = displays()
                host = AnnotationHost(Path(get_workspace_root()))
                try:
                    mapped = {}
                    for selected in catalog.displays:
                        bounds = {k: getattr(selected, k) for k in ('x', 'y', 'width', 'height')}
                        matches = [d for d in host.displays if d['physical_bounds'] == bounds]
                        if len(matches) != 1:
                            raise RuntimeError('截图显示器与桌面浮层的物理坐标不匹配。')
                        mapped[selected.id] = selected, matches[0]['id']
                    self._hosts[host.identity] = host, mapped
                    return ExecutionAnnotationResult(annotation_id=host.identity, displays=catalog.displays)
                except BaseException:
                    host.close()
                    raise
            identity = command.annotation_id
            if command.action == 'stop':
                entry = self._hosts.pop(identity, None)
                if entry:
                    entry[0].close()
                return ExecutionAnnotationResult(annotation_id=identity)
            entry = self._hosts.get(identity)
            if entry is None:
                raise ValueError('桌面标注已关闭，请重新开启。')
            host, mapped = entry
            payload = {'action': command.action}
            if command.drawing is not None:
                if command.display_id not in mapped:
                    raise ValueError('标注显示器不属于该执行设备。')
                display, native_id = mapped[command.display_id]
                if display not in displays().displays:
                    host.close()
                    del self._hosts[identity]
                    raise ValueError('显示器布局已变化，请重新选择。')
                payload.update(display_id=native_id, drawing=command.drawing.model_dump())
            host.command(payload)
            return ExecutionAnnotationResult(annotation_id=identity)


execution_annotations = ExecutionAnnotations()
